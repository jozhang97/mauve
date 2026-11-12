"""Validate the curated demo's pinned chromosomes and packaged alignment."""
import gzip
import hashlib
import io
import json
from pathlib import Path

from Bio import SeqIO

ROOT = Path(__file__).resolve().parents[1] / 'demo/bsubtilis'


def test_curated_chromosomes_and_alignment():
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    genomes = manifest['genomes']
    assert [g['strain'] for g in genomes] == ['168', 'NCIB 3610', 'PY79', 'QB928', 'BSn5', 'RO-NN-1']
    assert [g['id'] for g in genomes] == list(range(1, 7))
    assert len({g['accession'] for g in genomes}) == 6
    for genome in genomes:
        raw = gzip.decompress((ROOT / genome['annotations']).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == genome['genbank_sha256']
        record = SeqIO.read(io.StringIO(raw.decode()), 'genbank')
        assert record.id == genome['chromosome']
        assert len(record) == genome['bases'] > 3_500_000
        assert record.annotations['topology'] == 'circular'
        assert record.annotations['organism'].startswith('Bacillus subtilis')
        assert hashlib.sha256(str(record.seq).upper().encode()).hexdigest() == genome['sequence_sha256']
        assert sum(f.type == 'CDS' for f in record.features) > 1000
        assert any(f.type == 'rRNA' for f in record.features)
        assert any(f.type == 'tRNA' for f in record.features)
    for asset in (manifest['alignment'], manifest['alignment']['backbone']):
        raw = gzip.decompress((ROOT / asset['file']).read_bytes())
        assert len(raw) == asset['bytes']
        assert hashlib.sha256(raw).hexdigest() == asset['sha256']
        assert b'/tmp/' not in raw and b'/Users/' not in raw
    raw = gzip.decompress((ROOT / manifest['alignment']['file']).read_bytes())
    assert raw.splitlines().count(b'=') == manifest['alignment']['blocks'] > 1
    assert manifest['total_bases'] == sum(g['bases'] for g in genomes)


def test_reference_evidence_and_origin_regions():
    static = ROOT.parents[1] / 'mauve_web/static'
    snapshot = json.loads((static / 'essentiality-bsubtilis.json').read_text())
    origins = json.loads((static / 'doric-demo.json').read_text())
    assert snapshot['source']['input_rows'] == 257
    assert snapshot['source']['counts'] == {'essential': 257}
    table = ROOT.parents[1] / 'data/essentiality/koo-2017-bsubtilis.tsv'
    assert hashlib.sha256(table.read_bytes()).hexdigest() == snapshot['source']['table_sha256']
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    from mauve_web.annotations import parse_genbank
    for genome in manifest['genomes']:
        raw = gzip.decompress((ROOT / genome['annotations']).read_bytes())
        record = SeqIO.read(io.StringIO(raw.decode()), 'genbank')
        sequence = str(record.seq).upper()
        origin, = origins['records'][record.id]
        assert origin['sha256'] == genome['sequence_sha256']
        assert origin['length'] == len(record)
        dna, = [f for f in record.features if f.type == 'CDS' and f.qualifiers.get('gene') == ['dnaA']]
        assert origin['start'] == int(dna.location.end) + 1
        for region in origin['regions']:
            start, end = region['start'], region['end']
            bases = sequence[start - 1:end] if start <= end else sequence[start - 1:] + sequence[:end]
            assert hashlib.sha256(bases.encode()).hexdigest() == region['sequence_sha256']
            assert start - region['reported_start'] in (0, 1)
        parsed = parse_genbank(raw.decode(), [{'start': 1, 'end': 100, 'strand': '+', 'sequence': sequence[:100]}])
        assert parsed['records'][0]['replication_origin'] == origin['start']
        assert 'oriC2' in parsed['records'][0]['replication_origin_source']
        matches = [e for f in record.features if f.type == 'CDS'
                   for e in snapshot['sequences'].get(hashlib.sha256(str(f.extract(record.seq)).upper().encode()).hexdigest(), [])]
        assert len(matches) > 0
        if genome['strain'] == '168':
            assert len(matches) == 257
        if genome['strain'] == 'BSn5':
            assert origin['start'] > 2_000_000


def test_saved_server_demo_refreshes_origin_evidence(tmp_path):
    import sqlite3
    from fastapi.testclient import TestClient
    from mauve_web.app import create_app
    client = TestClient(create_app(data_dir=tmp_path))
    response = client.post('/api/demo?organism=bsubtilis')
    assert response.status_code == 200
    aid = response.json()['id']
    with sqlite3.connect(tmp_path / 'alignments.sqlite3') as db:
        metadata = json.loads(db.execute('SELECT metadata FROM annotation_sources WHERE alignment_id=? AND genome_id=1', (aid,)).fetchone()[0])
        metadata['demo_evidence_version'] = 1
        del metadata['records'][0]['replication_origin']
        db.execute('UPDATE annotation_sources SET metadata=? WHERE alignment_id=? AND genome_id=1', (json.dumps(metadata), aid))
    response = client.post('/api/demo?organism=bsubtilis')
    assert response.status_code == 200 and response.json()['id'] == aid
    sources = client.get(f'/api/alignments/{aid}/annotations').json()
    source, = [s for s in sources if s['genome_id'] == 1]
    assert source['metadata']['demo_evidence_version'] == 2
    assert source['metadata']['records'][0]['replication_origin'] == 1751
