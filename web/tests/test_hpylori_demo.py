"""Validate the curated demo's pinned chromosomes and packaged alignment."""
import gzip
import hashlib
import io
import json
from pathlib import Path

from Bio import SeqIO

ROOT = Path(__file__).resolve().parents[1] / 'demo/hpylori'


def test_curated_chromosomes_and_alignment():
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    genomes = manifest['genomes']
    assert [g['strain'] for g in genomes] == ['26695', 'J99', 'G27', 'HPAG1', 'P12', 'Shi470']
    assert [g['id'] for g in genomes] == list(range(1, 7))
    assert len({g['accession'] for g in genomes}) == 6
    for genome in genomes:
        raw = gzip.decompress((ROOT / genome['annotations']).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == genome['genbank_sha256']
        record = SeqIO.read(io.StringIO(raw.decode()), 'genbank')
        assert record.id == genome['chromosome']
        assert len(record) == genome['bases'] > 1_500_000
        assert record.annotations['topology'] == 'circular'
        assert record.annotations['organism'].startswith('Helicobacter pylori')
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


def test_origin_anchors_and_assay_evidence_are_sequence_verified():
    static = ROOT.parents[1] / 'mauve_web/static'
    origins = json.loads((static / 'doric-demo.json').read_text())
    snapshot = json.loads((static / 'essentiality-hpylori.json').read_text())
    assert snapshot['source']['input_rows'] == 45
    assert snapshot['source']['counts'] == {'essential': 33, 'nonessential': 11, 'ambiguous_reference_sequence': 1}
    table = ROOT.parents[1] / 'data/essentiality/chalker-2001-hpylori.tsv'
    assert hashlib.sha256(table.read_bytes()).hexdigest() == snapshot['source']['table_sha256']
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    from mauve_web.annotations import parse_genbank
    for genome in manifest['genomes']:
        raw = gzip.decompress((ROOT / genome['annotations']).read_bytes())
        record = SeqIO.read(io.StringIO(raw.decode()), 'genbank')
        entry, = origins['records'][record.id]
        assert entry['sha256'] == genome['sequence_sha256']
        assert entry['length'] == len(record)
        dna, = [f for f in record.features if f.type == 'CDS' and f.qualifiers.get('gene') == ['dnaA']]
        assert (entry['end'] == int(dna.location.start) if dna.location.strand == 1 else entry['start'] == int(dna.location.end) + 1)
        parsed = parse_genbank(raw.decode(), [{'start': 1, 'end': 100, 'strand': '+', 'sequence': str(record.seq[:100])}])
        assert parsed['records'][0]['replication_origin'] == entry['start']
        assert 'oriC1' in parsed['records'][0]['replication_origin_source']
        if genome['strain'] == '26695':
            matches = [e for f in record.features if f.type == 'CDS' for e in snapshot['sequences'].get(hashlib.sha256(str(f.extract(record.seq)).upper().encode()).hexdigest(), [])]
            assert sum(e['status'] == 'essential' for e in matches) == 31
