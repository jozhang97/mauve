"""Build diagnostic engines with identical inclusive function timers.

Restores patched source bytes after building; production assets are untouched.
Do not run another build against the same checkout concurrently.
"""
import argparse
import concurrent.futures
import importlib.util
from pathlib import Path
import re
import subprocess
import json
import hashlib
import sys

HERE = Path(__file__).resolve().parent
WEB = HERE.parents[1]

def instrument(root, saved, coverage_ranges=False):
    targets = {
        'mauveAligner/src/progressiveMauve.cpp': [('main', 0), ('applyBackbone', 1)],
        'libMems/libMems/ProgressiveAligner.cpp': [(f'ProgressiveAligner::{name}', i) for name, i in [
            ('align', 2), ('CreatePairwiseBPDistance', 3), ('getAlignment', 4),
            ('alignProfileToProfile', 5), ('doGappedAlignment', 6), ('recurseOnPairs', 7)]],
        'libMems/libMems/Backbone.cpp': [('makeAllPairwiseGenomeHSS', 8)],
        'libMems/libMems/MuscleInterface.cpp': [('MuscleInterface::Refine', 9), ('MuscleInterface::ProfileAlign', 10), ('MuscleInterface::Align', 11), ('MuscleInterface::RefineFast', 12), ('MuscleInterface::ProfileAlignFast', 13)],
        'libMems/libMems/DistanceMatrix.h': [('SingleCopyDistanceMatrix', 14)],
        'libMems/libMems/SeedOccurrenceList.h': [('construct', 15)],
        'muscle/libMUSCLE/nwsmall.cpp': [('NWSmall', 16)],
        'muscle/libMUSCLE/treefrommsa.cpp': [('TreeFromMSA', 17)],
        'muscle/libMUSCLE/refinew.cpp': [('RefineW', 18)],
        'muscle/libMUSCLE/refinehoriz.cpp': [('RefineHoriz', 19)]}
    for relative, functions in targets.items():
        path = root / relative
        saved[path] = path.read_bytes()
        text = path.read_text()
        if coverage_ranges and relative == 'libMems/libMems/DistanceMatrix.h':
            from coverage_patch import candidate
            text = '#include "' + str(HERE / 'coverage_bitmap.h') + '"\n' + candidate(text)
        for name, index in functions:
            pattern = r'(^[^\n;{}]*\b' + re.escape(name) + r'\s*\([^;{}]*\)\s*\{)'
            addition = '\n' + ('mauve_profile::Report mauve_report;\n' if index == 0 else '') + f'mauve_profile::Scope mauve_scope({index});\n'
            text, count = re.subn(pattern, lambda m: m[0] + addition, text, flags=re.M)
            if not count:
                raise RuntimeError(f'Missing function: {relative}: {name}')
        path.write_text(f'#include "{HERE / "stages.h"}"\n' + text)

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--target', choices=['native', 'browser'], required=True)
    p.add_argument('--coverage-ranges', action='store_true', help='Experimental ungapped coverage range updates')
    p.add_argument('--mimalloc', action='store_true', help='Browser allocator experiment')
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    sys.path.insert(0, str(WEB / 'wasm'))
    spec = importlib.util.spec_from_file_location('profile_build', WEB / ('native' if a.target == 'native' else 'wasm') / 'build.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    if a.mimalloc and a.target != 'browser':
        p.error('--mimalloc requires --target browser')
    saved = {}
    original_run = subprocess.run
    def run(command, *args, **kwargs):
        if a.mimalloc and command[0] == 'em++' and '-c' not in command:
            command = [*command, '-sMALLOC=mimalloc']
        return original_run(command, *args, **kwargs)
    subprocess.run = run
    original_pool = concurrent.futures.ThreadPoolExecutor
    def pool(*args, **kwargs):
        instrument(a.work.resolve(), saved, a.coverage_ranges)
        return original_pool(*args, **kwargs)
    concurrent.futures.ThreadPoolExecutor = pool
    try:
        if a.target == 'native':
            builder.build(a.work.resolve(), a.output.resolve(), Path('/opt/homebrew/opt/libomp'), 8)
        else:
            builder.build(a.work.resolve(), a.output.resolve(), 8, profiling=True, threaded=True)
        (a.output / 'STAGE_PROFILE.json').write_text(json.dumps({'description': 'Diagnostic build: inclusive aggregate wall milliseconds, nested scopes overlap.', 'coverage_ranges': a.coverage_ranges, 'allocator': 'mimalloc' if a.mimalloc else 'default', 'instrumentation_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [HERE / 'build.py', HERE / 'stages.h', HERE / 'coverage_patch.py', HERE / 'coverage_bitmap.h']}}, indent=2) + '\n')
    finally:
        concurrent.futures.ThreadPoolExecutor = original_pool
        subprocess.run = original_run
        for path, content in saved.items():
            path.write_bytes(content)
