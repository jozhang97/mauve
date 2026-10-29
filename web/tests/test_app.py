from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mauve_web.app import create_app
from mauve_web.xmfa import column_slice, parse_xmfa

FIXTURE = Path(__file__).resolve().parents[2] / 'testdata/small.alignment'
REVERSE = '> 1:10-12 + first.fa\nAC-G\n> 2:21-23 - second.fa\nA-TG\n=\n'


def test_original_yeast_fixture():
    data = parse_xmfa(FIXTURE.read_text())
    assert [g['extent'] for g in data['genomes']] == [693, 2000]
    assert len(data['blocks']) == 5
    assert len(data['blocks'][0]['members']) == 2
    assert data['genomes'][0]['name'] == 'S_bayanus_small.fasta'


def test_reverse_coordinates_gaps_and_page_offset():
    members = parse_xmfa(REVERSE)['blocks'][0]['members']
    assert column_slice(members[0], 0, 4)['positions'] == [10, 11, None, 12]
    assert column_slice(members[1], 0, 4)['positions'] == [23, None, 22, 21]
    sliced = column_slice(members[1], 2, 2)
    assert sliced['bases'] == 'TG'
    assert sliced['positions'] == [22, 21]


@pytest.mark.parametrize('text', [
    '', 'not an alignment', '> 1:1-5 +\nACG\n=',
    '> 1:1-3 +\nACG\n> 2:1-2 +\nAC\n=',
    '> 1:1-3 +\nACG\n> 1:1-3 +\nACG\n=',
    '> 1:3-1 -\nACG\n=', '> 0:1-3 +\nACG\n=',
    '> 1:0-0 +\nACG\n=', '> 1:1-3 +\nXYZ\n=',
])
def test_rejects_invalid_alignment(text):
    with pytest.raises(ValueError):
        parse_xmfa(text)


def test_absent_record_and_no_final_delimiter():
    parsed = parse_xmfa('> 1:1-3 +\nACG\n> 2:0-0 +\n---')
    assert len(parsed['blocks'][0]['members']) == 1
    assert len(parsed['genomes']) == 1


def test_api_import_persistence_and_pagination(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert client.get('/').status_code == 200
    assert client.get('/static/app.js').status_code == 200
    assert client.get('/api/alignments').json() == []
    response = client.post('/api/alignments?name=reverse.xmfa', content=REVERSE)
    assert response.status_code == 201
    aid = response.json()['id']
    blocks = client.get(f'/api/alignments/{aid}/blocks').json()
    assert 'sequence' not in blocks[0]['members'][0]
    page = client.get(f'/api/alignments/{aid}/blocks/1?offset=2&limit=2').json()
    assert page['members'][1]['positions'] == [22, 21]
    for suffix in ['offset=4', 'offset=-1', 'limit=501']:
        assert client.get(f'/api/alignments/{aid}/blocks/1?{suffix}').status_code == 422
    restarted = TestClient(create_app(tmp_path))
    assert restarted.get(f'/api/alignments/{aid}').json()['name'] == 'reverse.xmfa'
    assert len(restarted.get('/api/alignments').json()) == 1
    assert client.get('/api/alignments/missing').status_code == 404
    assert client.get(f'/api/alignments/{aid}/blocks/99').status_code == 404


def test_failed_import_is_atomic_and_demo_is_reusable(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert client.post('/api/alignments', content='bad').status_code == 422
    assert client.post('/api/alignments', content=b'\xff').status_code == 422
    assert client.get('/api/alignments').json() == []
    first = client.post('/api/demo')
    assert first.status_code == 200
    assert client.post('/api/demo').json()['id'] == first.json()['id']


def test_upload_limit(tmp_path, monkeypatch):
    monkeypatch.setattr('mauve_web.app.MAX_ALIGNMENT', 8)
    client = TestClient(create_app(tmp_path))
    assert client.post('/api/alignments', content='123456789').status_code == 413
    assert client.get('/api/alignments').json() == []


def test_identity_profile_coordinates_and_missing_data(tmp_path):
    from mauve_web.xmfa import identity_profile
    data = parse_xmfa('> 1:1-5 +\nAC-NTA\n> 2:10-14 -\nATGN-A\n=')['blocks'][0]
    profile = identity_profile(data, 1, bins=3)
    windows = profile['members'][0]['windows']
    assert windows == [
        {'start': 13, 'end': 14, 'identity': .5, 'compared': 2, 'columns': 2},
        {'start': 11, 'end': 12, 'identity': None, 'compared': 0, 'columns': 2},
        {'start': 10, 'end': 10, 'identity': 1.0, 'compared': 1, 'columns': 2},
    ]
    assert identity_profile(data, 3)['present'] is False
    client = TestClient(create_app(tmp_path))
    aid = client.post('/api/alignments', content=REVERSE).json()['id']
    path = f'/api/alignments/{aid}/blocks/1/profile'
    result = client.get(path, params={'reference_id': 1, 'bins': 2})
    assert result.status_code == 200
    assert result.json()['members'][0]['windows'][0]['start'] == 23
    assert client.get(path, params={'reference_id': 1, 'bins': 201}).status_code == 422
    assert client.get(path, params={'reference_id': 999}).status_code == 404


def test_next_difference_skips_matching_columns(tmp_path):
    client = TestClient(create_app(tmp_path))
    dna = 'A' * 200 + 'C' + 'A' * 20
    other = 'A' * 221
    aid = client.post('/api/alignments', content=f'> 1:1-221 +\n{dna}\n> 2:1-221 +\n{other}\n=').json()['id']
    path = f'/api/alignments/{aid}/blocks/1/next-difference'
    assert client.get(path + '?after=100').json() == {'offset': 200}
    assert client.get(path + '?after=201').json() == {'offset': None}
    assert client.get(path + '?after=-1').status_code == 422


def test_genomic_position_navigation_handles_gaps_and_reverse(tmp_path):
    from mauve_web.xmfa import coordinate_column
    members = parse_xmfa(REVERSE)['blocks'][0]['members']
    assert [coordinate_column(members[0], p) for p in [10, 11, 12]] == [0, 1, 3]
    assert [coordinate_column(members[1], p) for p in [23, 22, 21]] == [0, 2, 3]
    with pytest.raises(ValueError):
        coordinate_column(members[1], 24)
    client = TestClient(create_app(tmp_path))
    aid = client.post('/api/alignments', content=REVERSE).json()['id']
    path = f'/api/alignments/{aid}/blocks/1'
    result = client.get(path, params={'genome_id': 2, 'position': 22, 'limit': 1}).json()
    assert result['offset'] == 2
    assert result['members'][1]['positions'] == [22]
    assert result['members'][0]['positions'] == [None]
    for params in [{'genome_id': 2}, {'position': 22}, {'genome_id': 2, 'position': 24},
                   {'genome_id': 999, 'position': 1}, {'genome_id': 2, 'position': 0}]:
        assert client.get(path, params=params).status_code == 422


def test_streamed_import_rolls_back_and_overviews_migrate(tmp_path):
    import sqlite3
    client = TestClient(create_app(tmp_path))
    invalid = REVERSE + '> 1:1-9 +\nAC\n=\n'
    assert client.post('/api/alignments', content=invalid).status_code == 422
    with sqlite3.connect(tmp_path / 'alignments.sqlite3') as db:
        assert db.execute('SELECT count(*) FROM blocks').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM block_overviews').fetchone()[0] == 0
    aid = client.post('/api/alignments', content=REVERSE).json()['id']
    expected = client.get(f'/api/alignments/{aid}/blocks').json()
    with sqlite3.connect(tmp_path / 'alignments.sqlite3') as db:
        db.execute('DROP TABLE block_overviews')
    migrated = TestClient(create_app(tmp_path))
    assert migrated.get(f'/api/alignments/{aid}/blocks').json() == expected
    # The overview is independent of the potentially large DNA JSON payload.
    with sqlite3.connect(tmp_path / 'alignments.sqlite3') as db:
        db.execute("UPDATE blocks SET members='not JSON'")
    assert migrated.get(f'/api/alignments/{aid}/blocks').json() == expected
    assert migrated.get(f'/api/alignments/{aid}/blocks.tsv').status_code == 200


def test_alignment_limit_is_separate_from_sequence_input_limit(tmp_path, monkeypatch):
    monkeypatch.setattr('mauve_web.app.MAX_UPLOAD', 8)
    client = TestClient(create_app(tmp_path))
    assert client.post('/api/alignments', content=REVERSE).status_code == 201
    assert client.post('/api/inputs', content='123456789').status_code == 413
