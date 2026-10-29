"""Scientific equivalence and memory bounds for accelerated read paths."""
from concurrent.futures import ThreadPoolExecutor
import random

import pytest

from mauve_web import xmfa
from mauve_web.cache import BlockCache, decoded_size


def member(sequence, gid, strand='+'):
    return {'genome_id': gid, 'start': 11,
            'end': 10 + len(sequence.replace('-', '')), 'strand': strand,
            'sequence': sequence}


def slow_profile(block, reference_id, bins):
    reference = next(m for m in block['members'] if m['genome_id'] == reference_id)
    width = max(1, (block['columns'] + bins - 1) // bins)
    results = []
    for m in block['members']:
        if m is reference:
            continue
        totals = dict(matches=0, substitutions=0, gap_columns=0, ambiguous_columns=0)
        windows = []
        for offset in range(0, block['columns'], width):
            part = xmfa.column_slice(m, offset, width)
            positions = [p for p in part['positions'] if p is not None]
            matches = comparable = 0
            for a, b in zip(part['bases'], reference['sequence'][offset:offset + width]):
                if a in 'ACGT' and b in 'ACGT':
                    comparable += 1
                    matches += a == b
                    totals['matches' if a == b else 'substitutions'] += 1
                else:
                    totals['gap_columns' if '-' in (a, b) else 'ambiguous_columns'] += 1
            if positions:
                windows.append(dict(start=min(positions), end=max(positions),
                                    identity=matches / comparable if comparable else None,
                                    compared=comparable, columns=len(part['bases'])))
        results.append(dict(genome_id=m['genome_id'], windows=windows, **totals))
    return dict(reference_id=reference_id, present=True, members=results)


@pytest.mark.parametrize('bins', [1, 3, 100, 200])
def test_vector_profiles_match_scalar_rules(monkeypatch, bins):
    monkeypatch.setattr(xmfa, 'SCAN_CHUNK', 17)
    rng = random.Random(2026)
    sequences = [''.join(rng.choices('ACGTRYSWKMBDHVN-', k=307)) for _ in range(9)]
    sequences.append('A' + '-' * 305 + 'T')
    block = dict(columns=307, members=[member(s, i + 1, '-' if i % 2 else '+')
                                      for i, s in enumerate(sequences)])
    for reference in [1, 2, 10]:
        assert xmfa.identity_profile(block, reference, bins) == slow_profile(block, reference, bins)


def test_coordinate_search_matches_every_non_gap_column():
    rng = random.Random(42)
    sequence = '---' + ''.join(rng.choices('ACGT---N', k=2000)) + '---'
    for strand in ['+', '-']:
        m = member(sequence, 1, strand)
        positions = xmfa.column_slice(m, 0, len(sequence))['positions']
        for column, position in enumerate(positions):
            if position is not None:
                assert xmfa.coordinate_column(m, position) == column


def test_difference_scan_chunk_edges_and_all_members(monkeypatch):
    monkeypatch.setattr(xmfa, 'SCAN_CHUNK', 17)
    sequences = ['A' * 70, 'A' * 34 + '-' + 'A' * 35, 'A' * 17 + 'N' + 'A' * 52]
    block = dict(columns=70, members=[member(s, i) for i, s in enumerate(sequences)])
    for after in range(72):
        expected = next((i for i in range(after, 70) if len({s[i] for s in sequences}) > 1), None)
        assert xmfa.next_difference(block, after) == expected
    block['members'] = block['members'][:1]
    assert xmfa.next_difference(block) is None


def test_cache_byte_budget_lru_oversized_and_failures():
    value = {'sequence': 'A' * 1000}
    size = decoded_size(value)
    cache = BlockCache(max_bytes=2 * size, max_entries=2)
    for key in ['a', 'b', 'a', 'c']:
        cache.get(key, lambda: value)
    assert list(cache.entries) == ['a', 'c']
    assert cache.bytes == 2 * size
    cache.get('oversized', lambda: {'sequence': 'A' * 10000})
    assert list(cache.entries) == ['a', 'c']
    with pytest.raises(ValueError):
        cache.get('failed', lambda: int('invalid'))
    assert 'failed' not in cache.entries


def test_cache_coalesces_concurrent_loads():
    cache = BlockCache()
    calls = []
    def load():
        calls.append(1)
        return {'sequence': 'ACGT'}
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: cache.get(('alignment', 1), load), range(16)))
    assert len(calls) == 1
    assert all(r is results[0] for r in results)
