"""Build the browser pthread C++ code under native Apple Silicon ThreadSanitizer.

Run the regular --threaded build first. This tests C++ races, not browser runtime
or service-worker behavior. Requires a working ARM64 TSan clang (CLT clang 21 on
macOS 27; Xcode clang 17's sanitizer crashes even for an empty program there).
"""
import argparse
import platform
from pathlib import Path
import concurrent.futures, hashlib, re, subprocess
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--work', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--compiler-directory', type=Path, default=Path('/Library/Developer/CommandLineTools/usr/bin'))
parser.add_argument('--jobs', type=int, default=8)
args=parser.parse_args()
if platform.system() != 'Darwin' or platform.machine() != 'arm64':
    parser.error('This diagnostic target requires Apple Silicon macOS')
root=args.work.resolve()
if not (root/'.mauve-threaded-work').exists() or args.jobs < 1:
    parser.error('Use an existing --threaded build checkout and positive --jobs')
repo=Path(__file__).resolve().parents[1]
boost=root/'boost_1_65_1'
def sources(folder,key):
    text=(folder/'Makefile.am').read_text().replace('\\\n',' ')
    return [folder/f for f in re.search(r'^'+key+r'\s*=([^\n]+)',text,re.M)[1].split()]
files=sources(root/'libGenome/libGenome','LIBGENOME_SRC')+sources(root/'muscle/libMUSCLE','LIBMUSCLE_SRC')
for key in ['LIBMEMS_SRC','HOMOLOGYHMM_SRC','DMSML_SRC']:files+=sources(root/'libMems/libMems',key)
files += [root/'mauveAligner/src'/f for f in ['progressiveMauve.cpp','UniqueMatchFinder.cpp']]
files += list((boost/'libs/filesystem/src').glob('*.cpp'))+[boost/'libs/system/src/error_code.cpp',boost/'libs/iostreams/src/mapped_file.cpp']
files += [repo/'wasm/optimizations'/f for f in ['profile_row.cpp','seed_lookup.cpp','thread_pool.cpp']]
sdk=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
flags=['-isysroot',sdk,'-O1','-g','-fsanitize=thread','-fno-omit-frame-pointer','-DNDEBUG','-D_LIB','-DUSE_LIBC','-DBOOST_NO_CXX11_SCOPED_ENUMS','-D__EMSCRIPTEN_PTHREADS__','-ffp-contract=off','-I'+str(repo/'native/include'),'-I'+str(repo/'wasm/optimizations'),'-Wno-deprecated-declarations','-Wno-register','-Wno-inconsistent-missing-override','-Wno-c++11-narrowing','-DMAUVE_PROFILE_ROWS','-DMAUVE_FAST_TRANSLATE','-DMAUVE_SEED_LOOKUP','-DMAUVE_COMPACT_TRACE','-DMAUVE_LAZY_TRACE','-DMAUVE_ROW_GAPS','-DMAUVE_LOCAL_D_SCORE']
flags+=['-I'+str(root/f) for f in ['libGenome','muscle','libMems','boost_1_65_1']]
obj=root/'objects-pthread-tsan';obj.mkdir(exist_ok=True)
def compile(file):
    dest=obj/(hashlib.sha256(str(file).encode()).hexdigest()[:16]+'.o')
    cc=str(args.compiler_directory/('clang' if file.suffix=='.c' else 'clang++'))
    extra=['-Wno-error=implicit-function-declaration'] if file.suffix=='.c' else ['-std=c++14']
    subprocess.run([cc,*flags,*extra,'-c',str(file),'-o',str(dest)],check=True)
    return dest
with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:objects=list(pool.map(compile,files))
subprocess.run([str(args.compiler_directory/'clang++'),*map(str,objects),'-isysroot',sdk,'-fsanitize=thread','-o',str(args.output.resolve())],check=True)
