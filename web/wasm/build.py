"""Rebuild progressiveMauve with Emscripten 4.0.15 (emcc/em++ must be on PATH).
Pinned upstream sources are downloaded into --work; no system packages change.
"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request

PINS = {
    'mauveAligner': '3e8293836119a8a6cc883b48f234947cf55387c5',
    'libMems': '1f067601ae48f898dc3c9b92a3b7bf636d04fc70',
    'libGenome': '41b5c8bc02048f41dbd0d1e116b3bca8b4a384db',
    'muscle': 'ec6ab52e7a667e9d2fa70e89b3d2d9adb81f074e',
}
BOOST_SHA256 = '9807a5d16566c57fd74fb522764e0b134a8bbe6b6e8967b83afefd30dcd3be81'
HERE = Path(__file__).resolve().parent


def build(root, output, workers):
    version = subprocess.check_output(['emcc', '--version'], text=True)
    if '4.0.15' not in version:
        raise RuntimeError('Use Emscripten 4.0.15 for this pinned build.')
    root.mkdir(parents=True, exist_ok=True)
    for name, revision in PINS.items():
        dest = root / name
        if not dest.exists():
            subprocess.run(['git', 'clone', 'https://github.com/koadman/' + name + '.git', str(dest)], check=True)
        actual = subprocess.check_output(['git', '-C', str(dest), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != revision:
            subprocess.run(['git', '-C', str(dest), 'checkout', '--detach', revision], check=True)
    boost = root / 'boost_1_65_1'
    if not boost.exists():
        archive = root / 'boost.tar.bz2'
        urllib.request.urlretrieve('https://archives.boost.io/release/1.65.1/source/boost_1_65_1.tar.bz2', archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != BOOST_SHA256:
            raise RuntimeError('Boost checksum mismatch')
        with tarfile.open(archive) as tar:
            tar.extractall(root, filter='data')
    # Minimal compatibility fixes; alignment/scoring algorithms are unchanged.
    def patch(path, old, new):
        source = path.read_text()
        if old in source:
            path.write_text(source.replace(old, new))
        elif new not in source:
            raise RuntimeError('Patch target changed: ' + str(path))
    patch(boost / 'boost/type_traits/remove_pointer.hpp', '#include <boost/config.hpp>\n\n',
          '#include <boost/config.hpp>\n#include <boost/config/workaround.hpp>\n\n')
    path = root / 'libMems/libMems/CompactGappedAlignment.h'
    patch(path, 'void swap( mems::CompactGappedAlignment<>& a, mems::CompactGappedAlignment<>& b )\n',
          'void swap( mems::CompactGappedAlignment<>& a, mems::CompactGappedAlignment<>& b ) noexcept(is_nothrow_move_constructible<mems::CompactGappedAlignment<>>::value && is_nothrow_move_assignable<mems::CompactGappedAlignment<>>::value)\n')
    path = root / 'libMems/libMems/dmSML/asyncio.c'
    patch(path, '#include <string.h>\n\n', '#include <string.h>\n#include <sys/stat.h>\n\n')
    source = path.read_text()
    if '#error "libc aStatSize not implemented"' in source:
        source = source.replace('#error "libc aStatSize not implemented"', 'struct stat data; return stat(path, &data) ? 0 : data.st_size;', 1)
        source = source.replace('#error "libc aStatSize not implemented"', 'return aStatFileSize(path) / sizeof(record_t);', 1)
        path.write_text(source)
    def sources(folder, key):
        text = (folder / 'Makefile.am').read_text().replace('\\\n', ' ')
        return [folder / f for f in re.search(r'^' + key + r'\s*=([^\n]+)', text, re.M)[1].split()]
    files = sources(root / 'libGenome/libGenome', 'LIBGENOME_SRC') + sources(root / 'muscle/libMUSCLE', 'LIBMUSCLE_SRC')
    for key in ['LIBMEMS_SRC', 'HOMOLOGYHMM_SRC', 'DMSML_SRC']:
        files += sources(root / 'libMems/libMems', key)
    files += [root / 'mauveAligner/src' / f for f in ['progressiveMauve.cpp', 'UniqueMatchFinder.cpp']]
    files += list((boost / 'libs/filesystem/src').glob('*.cpp')) + [boost / 'libs/system/src/error_code.cpp', boost / 'libs/iostreams/src/mapped_file.cpp']
    flags = ['-O3', '-msimd128', '-DNDEBUG', '-D_LIB', '-DUSE_LIBC', '-DBOOST_NO_CXX11_SCOPED_ENUMS',
             '-Wno-deprecated-declarations', '-Wno-register', '-Wno-inconsistent-missing-override', '-Wno-c++11-narrowing']
    flags += ['-I' + str(root / f) for f in ['libGenome', 'muscle', 'libMems', 'boost_1_65_1']]
    obj = root / 'objects'; obj.mkdir(exist_ok=True)
    def compile_one(file):
        dest = obj / (str(file.relative_to(root)).replace('/', '_') + '.o')
        compiler = 'emcc' if file.suffix == '.c' else 'em++'
        extra = ['-Wno-error=implicit-function-declaration'] if file.suffix == '.c' else ['-std=c++14', '-fexceptions']
        # Always compile: changes to dependency headers must invalidate objects too.
        subprocess.run([compiler, *flags, *extra, '-c', str(file), '-o', str(dest)], check=True)
        return dest
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        objects = list(pool.map(compile_one, files))
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(['em++', *map(str, objects), '-O3', '-msimd128', '-fexceptions', '-sDISABLE_EXCEPTION_CATCHING=0',
                    '-sALLOW_MEMORY_GROWTH=1', '-sMAXIMUM_MEMORY=2147483648', '-sSTACK_SIZE=8388608',
                    '-sMODULARIZE=1', '-sEXPORT_ES6=1', '-sINVOKE_RUN=0', "-sEXPORTED_RUNTIME_METHODS=['FS','callMain']",
                    '-sFORCE_FILESYSTEM=1', '-sENVIRONMENT=web,worker,node', '-o', str(output / 'progressiveMauve.mjs')], check=True)
    for name in PINS:
        shutil.copyfile(root / name / 'COPYING', output / (name + '-COPYING'))
    shutil.copyfile(root / 'libMems/LICENSE', output / 'libMems-LICENSE')
    shutil.copyfile(boost / 'LICENSE_1_0.txt', output / 'Boost-LICENSE')
    manifest = {'compiler': 'Emscripten 4.0.15', 'sources': {name: {'url': 'https://github.com/koadman/' + name, 'revision': rev} for name, rev in PINS.items()},
                'boost': {'url': 'https://archives.boost.io/release/1.65.1/source/boost_1_65_1.tar.bz2', 'sha256': BOOST_SHA256},
                'wasm_sha256': hashlib.sha256((output / 'progressiveMauve.wasm').read_bytes()).hexdigest(),
                'rebuild': 'python3 build.py --work /tmp/mauve-wasm-build --output ./rebuilt'}
    (output / 'SOURCES.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=HERE.parent / 'mauve_web/static/wasm')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    build(args.work.resolve(), args.output.resolve(), args.jobs)
