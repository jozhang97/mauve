"""Compare real engines in fresh processes, checking every output artifact byte.

python3 web/benchmarks/compare-engines.py --baseline /tmp/baseline/progressiveMauve.mjs \
    --candidate web/mauve_web/static/wasm/progressiveMauve.mjs --output /tmp/results.json
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import statistics
import subprocess


def compare(baseline, candidate, repeats, output, quick=False, genomes=None, bases=100000, timeout=600, case=None):
    runner = Path(__file__).with_name('engine.mjs')
    cases = [('similar', 12, 100000), ('divergent', 4, 20000),
             ('rearranged', 4, 50000), ('repeats', 4, 50000), ('ambiguous', 4, 20000)]
    if case is not None:
        cases = [entry for entry in cases if entry[0] == case]
    if quick:
        cases = [(kind, 3, 5000) for kind, _, _ in cases]
    if genomes is not None:
        cases = [('similar', genomes, bases)]
    report = {'platform': platform.platform(), 'machine': platform.machine(),
              'measured_at': datetime.now(timezone.utc).isoformat(),
              'node': subprocess.check_output(['node', '--version'], text=True).strip(),
              'baseline': str(baseline), 'candidate': str(candidate),
              'wasm_sha256': {label: hashlib.sha256(path.with_suffix('.wasm').read_bytes()).hexdigest()
                              for label, path in [('baseline', baseline), ('candidate', candidate)]},
              'cases': []}
    for kind, genomes, bases in cases:
        runs = {'baseline': [], 'candidate': []}
        expected = None
        for repeat in range(repeats):
            # Alternate order to reduce systematic warmup/temperature bias.
            order = [('baseline', baseline), ('candidate', candidate)]
            if repeat % 2:
                order.reverse()
            for label, engine in order:
                command = ['node', str(runner), str(engine), kind, str(genomes), str(bases)]
                result = json.loads(subprocess.check_output(command, text=True, timeout=timeout))
                if expected is None:
                    expected = result['artifacts']
                if result['artifacts'] != expected:
                    raise RuntimeError(f'Output mismatch: {kind}, {label}, repeat {repeat}')
                runs[label].append(result)
                print(f'{kind} {label}: {result["alignment_ms"]:.1f} ms', flush=True)
                # Retain completed measurements even if the next engine fails.
                report['in_progress'] = {'kind': kind, 'genomes': genomes, 'bases': bases, 'runs': runs}
                output.write_text(json.dumps(report, indent=2) + '\n')
        medians = {label: statistics.median(r['alignment_ms'] for r in values)
                   for label, values in runs.items()}
        report['cases'].append({'kind': kind, 'genomes': genomes, 'bases': bases,
                                'median_ms': medians, 'speedup': medians['baseline'] / medians['candidate'],
                                'artifacts_identical': True, 'runs': runs})
        report.pop('in_progress', None)
        output.write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--case', choices=['similar', 'divergent', 'rearranged', 'repeats', 'ambiguous'], help='Focus repeated measurements on one workload')
    parser.add_argument('--genomes', type=int, help='Run one similar-genome scaling case (2–128)')
    parser.add_argument('--bases', type=int, default=100000)
    parser.add_argument('--timeout', type=int, default=600, help='Timeout in seconds per engine run')
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    if args.genomes is not None and not 2 <= args.genomes <= 128:
        parser.error('--genomes must be between 2 and 128')
    if args.bases < 1000 or args.timeout < 1:
        parser.error('--bases must be at least 1000 and --timeout must be positive')
    compare(args.baseline.resolve(), args.candidate.resolve(), args.repeats, args.output,
            args.quick, args.genomes, args.bases, args.timeout, args.case)
