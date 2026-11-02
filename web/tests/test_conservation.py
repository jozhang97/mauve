import json
from pathlib import Path
import pytest
from mauve_web.conservation import build_conservation, sample_conservation, parse_backbone

FIXTURE = json.loads((Path(__file__).parents[1] / 'browser-tests/fixtures/conservation-java.json').read_text())

@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda c: c['name'])
def test_java_parity(case):
    members = [dict(genome_id=i+1, start=1, end=len(row.replace('-', '')), strand='-' if i in case.get('reverse', []) else '+', sequence=row) for i, row in enumerate(case['rows']) if row.replace('-', '')]
    genomes = [dict(id=i+1, extent=len(row.replace('-', '')) or 40) for i, row in enumerate(case['rows'])]
    block = dict(id=1, columns=len(case['rows'][0]), members=members)
    backbone = [dict(block_id=1, left=0, right=block['columns'], genomes=[i+1 for i in case['backbone']])] if 'backbone' in case else None
    indexes = build_conservation(genomes, [block], lambda b: b, backbone)
    for i, expected in enumerate(case['expected']):
        if not expected:
            continue
        hist = indexes[i+1][0]
        assert hist.levels[0][0].tolist() == expected['base']
        for left, right, mean, low, high in expected['queries']:
            assert [hist.value(left, right, kind) for kind in (0, -1, 1)] == [mean, low, high]


def test_short_regions_and_validation():
    genomes = [dict(id=i, extent=4) for i in (1, 2)]
    block = dict(id=1, columns=4, members=[dict(genome_id=i, start=1, end=4, strand='+', sequence='AAAA') for i in (1, 2)])
    indexes = build_conservation(genomes, [block], lambda b: b)
    assert sample_conservation(indexes, [dict(genome_id=1, start=1, end=4, bins=4)])[0]['samples'][0][0] > .99
    with pytest.raises(ValueError):
        sample_conservation(indexes, [dict(genome_id=1, start=1, end=4, bins=99999)])
    with pytest.raises(ValueError):
        parse_backbone('0 1 5 0 1', [block], genomes)


def test_overlapping_backbone_groups():
    rows = ['A'*40, 'A'*40, 'C'*40, 'T'*40]
    genomes = [dict(id=i+1, extent=40) for i in range(4)]
    block = dict(id=1, columns=40, members=[dict(genome_id=i+1, start=1, end=40, strand='+', sequence=row) for i, row in enumerate(rows)])
    bb = parse_backbone('0 1 40 0 1\n0 1 40 2 3', [block], genomes)
    indexes = build_conservation(genomes, [block], lambda b: b, bb)
    assert indexes[1][0].value(1, 40) == 127
    assert indexes[3][0].value(1, 40) == -128
    with pytest.raises(ValueError):
        parse_backbone('0 1 40 0 1\n0 1 40 1 2', [block], genomes)


def test_api_backbone_replaces_cached_index_and_survives_restart(tmp_path):
    from fastapi.testclient import TestClient
    from mauve_web.app import create_app
    raw = ''.join(f'> {i+1}:1-40 + g{i+1}\n{base*40}\n' for i, base in enumerate('AAT')) + '=\n'
    with TestClient(create_app(tmp_path)) as client:
        imported = client.post('/api/alignments', content=raw)
        assert imported.status_code == 201
        aid = imported.json()['id']
        url = f'/api/alignments/{aid}'
        ranges = [dict(genome_id=1, start=1, end=40, bins=4)]
        before = client.post(url + '/conservation', json=ranges).json()
        assert before[0]['samples'][0][0] < .1
        assert client.post(url + '/backbone', content='0 1 40 0 1').status_code == 200
        after = client.post(url + '/conservation', json=ranges).json()
        assert after[0]['samples'][0][0] > .99
        assert client.post(url + '/backbone', content='0 1 999 0 1').status_code == 422
        assert client.post(url + '/conservation', json=ranges).json() == after
        assert client.post(url + '/conservation', json=[dict(genome_id=1, start=1, end=40, bins=9000)]).status_code == 422
    with TestClient(create_app(tmp_path)) as client:
        assert client.post(url + '/conservation', json=ranges).json() == after
