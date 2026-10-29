"""Run from web/: .venv/bin/python benchmarks/backend.py

Synthetic data only; creates a temporary library and never touches user data.
Use --baseline /path/to/previous/xmfa.py to compare analysis implementations.
"""
import argparse
import importlib.util
from pathlib import Path
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from mauve_web.app import create_app
from mauve_web import xmfa


def measure(name, fn, repeats=3):
    samples = []
    for _ in range(repeats):
        start = perf_counter()
        fn()
        samples.append(perf_counter() - start)
    print(f'{name}: {median(samples) * 1000:.2f} ms (median, n={repeats})')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--columns', type=int, default=1_000_000)
    parser.add_argument('--genomes', type=int, default=8)
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    if args.columns < 2 or args.genomes < 2:
        parser.error('Use at least two columns and two genomes.')
    sequences = []
    for i in range(args.genomes):
        motif = 'ACGTN-' if i % 2 else 'ACGTA-'
        sequence = (motif * ((args.columns + 5) // 6))[:args.columns]
        sequences.append(f'> {i+1}:1-{len(sequence.replace("-", ""))} {"-" if i % 2 else "+"}\n{sequence}\n')
    raw = ''.join(sequences) + '=\n'
    block = xmfa.parse_xmfa(raw)['blocks'][0]
    print(f'{args.genomes} genomes x {args.columns:,} columns')
    implementations = [('optimized', xmfa)]
    if args.baseline:
        spec = importlib.util.spec_from_file_location('baseline', args.baseline)
        baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baseline)
        assert baseline.identity_profile(block, 1) == xmfa.identity_profile(block, 1)
        implementations.insert(0, ('baseline', baseline))
    for label, module in implementations:
        measure(f'{label} identity profile', lambda: module.identity_profile(block, 1))
        measure(f'{label} genomic jump', lambda: module.coordinate_column(block['members'][0], block['members'][0]['end']))
    identical = dict(columns=args.columns, members=[dict(m, sequence=block['members'][0]['sequence'])
                                                   for m in block['members']])
    measure('optimized next difference (full identical block)', lambda: xmfa.next_difference(identical))
    with TemporaryDirectory() as directory:
        client = TestClient(create_app(directory))
        response = client.post('/api/alignments', content=raw)
        response.raise_for_status()
        path = f'/api/alignments/{response.json()["id"]}/blocks/1'
        def request(suffix):
            client.get(path + suffix).raise_for_status()
        measure('API cold sequence page', lambda: request('?limit=100'), repeats=1)
        measure('API cached sequence page', lambda: request('?limit=100'))
        measure('API cached identity profile', lambda: request('/profile?reference_id=1'))


if __name__ == '__main__':
    main()
