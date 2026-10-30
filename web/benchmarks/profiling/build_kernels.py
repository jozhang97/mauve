"""Link identical standalone kernels against previously built diagnostic objects."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from coverage_patch import candidate

HERE = Path(__file__).resolve().parent
WEB = HERE.parents[1]

def build(root, output, native):
    output.mkdir(parents=True, exist_ok=True)
    text = (root / 'libMems/libMems/DistanceMatrix.h').read_text()
    def function(source, name):
        start = source.index('void SingleCopyDistanceMatrix(')
        end = source.index('}', source.index('\n\tTransformDistanceIdentity(distance);', start)) + 1
        return 'template<class MatchVector>\n' + source[start:end].replace('SingleCopyDistanceMatrix', name)
    (output / 'distance_variants.h').write_text('#include "libMems/DistanceMatrix.h"\nnamespace mems {\n' + function(text, 'SingleCopyDistanceReference') + '\n' + function(candidate(text), 'SingleCopyDistanceCandidate') + '\n}\n')
    flags = ['-O3', '-flto', '-std=c++14', '-DNDEBUG', '-D_LIB', '-DUSE_LIBC', '-DBOOST_NO_CXX11_SCOPED_ENUMS', '-Wno-deprecated-declarations', '-Wno-register', '-Wno-inconsistent-missing-override', '-Wno-c++11-narrowing', '-I'+str(HERE), '-I'+str(WEB/'wasm/optimizations'), '-I'+str(output)]
    flags += ['-I'+str(root/p) for p in ['libGenome', 'libMems', 'muscle', 'boost_1_65_1']]
    if native:
        sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
        flags += ['-ffp-contract=off', '-isysroot', sdk, '-Xpreprocessor', '-fopenmp', '-I/opt/homebrew/opt/libomp/include']
        excluded = {hashlib.sha256(str(p).encode()).hexdigest()[:16]+'.o' for p in [root/'mauveAligner/src/progressiveMauve.cpp', WEB/'native/main.cpp']}
        objects = [p for p in (root/'objects-native').glob('*.o') if p.name not in excluded]
        command = ['clang++', *flags, str(HERE/'kernels.cpp'), *map(str,objects), '-L/opt/homebrew/opt/libomp/lib', '-Wl,-rpath,/opt/homebrew/opt/libomp/lib', '-lomp', '-o', str(output/'kernels')]
    else:
        objects = [p for p in (root/'objects-optimized').glob('*.o') if p.name != 'mauveAligner_src_progressiveMauve.cpp.o']
        command = ['em++', *flags, '-msimd128', '-pthread', '-fwasm-exceptions', str(HERE/'kernels.cpp'), *map(str,objects), '-sPROXY_TO_PTHREAD=1', '-sPTHREAD_POOL_SIZE=1', '-sEXIT_RUNTIME=1', '-sSTACK_SIZE=8388608', '-sDEFAULT_PTHREAD_STACK_SIZE=8388608', '-sALLOW_MEMORY_GROWTH=1', '-sMODULARIZE=1', '-sEXPORT_ES6=1', '-sENVIRONMENT=web,worker', '-o', str(output/'kernels.mjs')]
    subprocess.run(command, check=True)
    (output/'BUILD.json').write_text(json.dumps({'command':command,'objects_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in objects},'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [HERE/'kernels.cpp',HERE/'coverage_bitmap.h',output/'distance_variants.h']}},indent=2)+'\n')

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--target',choices=['native','browser'],required=True)
    p.add_argument('--work',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    build(a.work.resolve(),a.output.resolve(),a.target=='native')
