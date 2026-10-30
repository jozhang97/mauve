"""Check native NEON scoring, seed packing, and the runtime thread bounds."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--work', type=Path, required=True)
p.add_argument('--engine', type=Path, default=HERE / 'bin/progressiveMauve')
a = p.parse_args()
root = a.work.resolve()
sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
flags = [os.environ.get('CXX', 'clang++'), '-isysroot', sdk, '-O3', '-flto', '-Wl,-dead_strip',
         '-std=c++14', '-ffp-contract=off', '-I' + str(HERE / 'include'),
         '-I' + str(HERE.parent / 'wasm/optimizations')]
flags += ['-I' + str(root / name) for name in ['muscle', 'libMems', 'libGenome', 'boost_1_65_1']]
with tempfile.TemporaryDirectory(prefix='mauve-native-kernels-') as directory:
    for name, sources in [
        ('profile_scores', [root / 'muscle/libMUSCLE/scorepp.cpp', HERE.parent / 'wasm/optimizations/profile_row.cpp']),
        ('seed_lookup', [HERE.parent / 'wasm/optimizations/seed_lookup.cpp']),
    ]:
        output = Path(directory) / name
        subprocess.run([*flags, str(HERE.parent / 'wasm/tests' / (name + '.cpp')),
                        *map(str, sources), '-o', str(output)], check=True)
        subprocess.run([str(output)], check=True)
for value in ['0', '17', '2,4', 'garbage', '1', '8', '16']:
    result = subprocess.run([str(a.engine.resolve()), '--version'], env=dict(os.environ, MAUVE_THREADS=value),
                            capture_output=True, text=True, timeout=10)
    expected = 0 if value in ['1', '8', '16'] else 2
    if result.returncode != expected:
        raise RuntimeError(f'Thread validation failed for {value}: {result.stderr}')
print('Thread counts validated: 1, 8, 16 accepted; invalid counts rejected.')
