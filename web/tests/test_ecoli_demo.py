"""Frozen demo provenance and whole-chromosome asset validation."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import random

from Bio import SeqIO

ROOT = Path(__file__).resolve().parents[1] / 'demo/ecoli'


def test_sample_is_reproducible_and_assets_match_manifest():
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    genomes = manifest['genomes']
    assert len(genomes) == len({g['strain'].casefold() for g in genomes}) == len({g['accession'] for g in genomes}) == 8
    pool = json.loads(gzip.decompress((ROOT / 'sampling-pool.json.gz').read_bytes()))
    assert len(pool) == manifest['eligible_strains']
    random.Random(int(manifest['seed'])).shuffle(pool)
    rejected = {r['accession'] for r in manifest['rejected']}
    assert [g['accession'] for g in genomes] == [g['accession'] for g in pool if g['accession'] not in rejected][:8]
    assert [g['id'] for g in genomes] == list(range(1, 9))
    for genome in genomes:
        raw = gzip.decompress((ROOT / genome['annotations']).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == genome['genbank_sha256']
        records = list(SeqIO.parse(io.StringIO(raw.decode()), 'genbank'))
        assert len(records) == 1
        record = records[0]
        assert record.id == genome['chromosome'] and len(record) == genome['bases']
        assert record.annotations['topology'] == 'circular'
        assert hashlib.sha256(str(record.seq).upper().encode()).hexdigest() == genome['sequence_sha256']
        assert sum(f.type == 'CDS' for f in record.features) > 3000
        assert any(f.type == 'rRNA' for f in record.features)
        assert any(f.type == 'tRNA' for f in record.features)
    raw = gzip.decompress((ROOT / manifest['alignment']['file']).read_bytes())
    assert hashlib.sha256(raw).hexdigest() == manifest['alignment']['sha256']
    assert len(raw) == manifest['alignment']['bytes']
    assert raw.splitlines().count(b'=') == manifest['alignment']['blocks']
    assert b'/tmp/' not in raw and b'/Users/' not in raw
