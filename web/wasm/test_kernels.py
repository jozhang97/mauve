"""Run C++ differential/regression tests after an optimized build.

Requires the pinned em++ on PATH and the same --work directory as build.py.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def test(root, cases=None):
    includes = ['-I' + str(root / p) for p in ('muscle', 'libMems', 'libGenome', 'boost_1_65_1')]
    flags = ['-O3', '-msimd128', '-flto', '-std=c++14', '-fwasm-exceptions',
             '-DMAUVE_FAST_TRANSLATE', '-DBOOST_NO_CXX11_SCOPED_ENUMS',
             '-I' + str(HERE / 'optimizations'), *includes]
    objects = sorted((root / 'objects-optimized').glob('*.o'))
    if not objects:
        raise RuntimeError('Run build.py with this --work directory first.')
    with tempfile.TemporaryDirectory(prefix='mauve-kernels-') as directory:
        traceback_objects = []
        # Compile both paths with test-only cell accessors. Compare every cell,
        # including cells that the final traceback path does not visit.
        for label in (['Reference', 'Candidate'] if cases is None or 'traceback' in cases else []):
            source = Path(directory) / ('traceback_' + label + '.cpp')
            source.write_text(
                ('#define NWSmall NWSmallReference\n' if label == 'Reference' else '') +
                '#include "' + str(root / 'muscle/libMUSCLE/nwsmall.cpp') + '"\n' +
                'namespace muscle { unsigned char TraceCell' + label +
                '(unsigned i, unsigned j) { return CacheTB.get()[i][j]; } }\n')
            output = source.with_suffix('.o')
            extra = ['-DMAUVE_COMPACT_TRACE', '-DMAUVE_LAZY_TRACE', '-DMAUVE_ROW_GAPS', '-DMAUVE_LOCAL_D_SCORE'] if label == 'Candidate' else []
            subprocess.run(['em++', *flags, '-DNDEBUG', '-D_LIB', '-DUSE_LIBC',
                            '-DMAUVE_PROFILE_ROWS', *extra, '-c', str(source), '-o', str(output)], check=True)
            traceback_objects.append(output)
        for name, sources in [
            ('profile_scores', [root / 'muscle/libMUSCLE/scorepp.cpp', HERE / 'optimizations/profile_row.cpp']),
            ('seed_lookup', [HERE / 'optimizations/seed_lookup.cpp']),
            ('traceback', [*traceback_objects, *[p for p in objects if p.name not in
                ['mauveAligner_src_progressiveMauve.cpp.o', 'muscle_libMUSCLE_nwsmall.cpp.o']]]),
            ('coordinates', [p for p in objects if p.name != 'mauveAligner_src_progressiveMauve.cpp.o']),
            ('homology_states', [p for p in objects if p.name != 'mauveAligner_src_progressiveMauve.cpp.o']),
        ]:
            if cases is not None and name not in cases:
                continue
            output = Path(directory) / (name + '.cjs')
            subprocess.run(['em++', *flags, str(HERE / 'tests' / (name + '.cpp')),
                            *map(str, sources), '-o', str(output)], check=True)
            subprocess.run(['node', str(output)], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--case', action='append', choices=['profile_scores', 'seed_lookup', 'traceback', 'coordinates', 'homology_states'],
                        help='Run only the named kernel; repeat to select several. Defaults to all kernels.')
    args = parser.parse_args()
    test(args.work.resolve(), args.case)
