"""Build the curated six-strain H. pylori demo from pinned NCBI assemblies.

Run web/.venv/bin/python web/demo/build_hpylori.py --align. Downloads are reused
only after their manifest checksums validate. Plasmids are excluded.
"""
import argparse
import gzip
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import time
import zipfile

import httpx
from Bio import SeqIO
import build_ecoli as builder

DEST = Path(__file__).resolve().parent / 'hpylori'
WORK = Path('/tmp/mauve-hpylori')
STRAINS = [('26695', 'GCF_000307795.1'), ('J99', 'GCF_000008785.1'),
           ('G27', 'GCF_000021165.1'), ('HPAG1', 'GCF_000013245.1'),
           ('P12', 'GCF_000021465.1'), ('Shi470', 'GCF_000020245.1')]


def prepare():
    DEST.mkdir(exist_ok=True)
    WORK.mkdir(exist_ok=True)
    manifest = {'id': 'hpylori-six-v1', 'name': 'H. pylori · 6-strain demo',
        'created': datetime.now(timezone.utc).isoformat(),
        'sampling': 'Curated complete annotated chromosomes: 26695, J99, G27, HPAG1, P12, Shi470. Pinned RefSeq assemblies; plasmids excluded.',
        'reference': 'https://pmc.ncbi.nlm.nih.gov/articles/PMC2952849/', 'genomes': []}
    previous = json.loads((DEST / 'manifest.json').read_text()) if (DEST / 'manifest.json').exists() else {}
    with httpx.Client(timeout=180, follow_redirects=True, headers={'User-Agent': 'MauveExplorer demo builder'}) as client:
        for gid, (strain, accession) in enumerate(STRAINS, 1):
            filename = f'{accession}.gbk.gz'
            cached = next((g for g in previous.get('genomes', []) if g['accession'] == accession), None)
            url = f'{builder.BASE}/genome/accession/{accession}/download'
            if cached and (DEST / filename).exists():
                gbk = gzip.decompress((DEST / filename).read_bytes())
                if hashlib.sha256(gbk).hexdigest() != cached['genbank_sha256']:
                    raise ValueError(f'Cached checksum mismatch: {accession}')
                record = SeqIO.read(io.StringIO(gbk.decode()), 'genbank')
                excluded = cached['excluded_records']
            else:
                print(f'Downloading {strain}: {accession}', flush=True)
                raw = builder.fetch(client, url, params={'include_annotation_type': 'GENOME_GBFF'}).content
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    files = [p for p in archive.namelist() if p.startswith(f'ncbi_dataset/data/{accession}/') and p.endswith('.gbff')]
                    if len(files) != 1:
                        raise ValueError(f'Expected one GenBank file: {files}')
                    records = list(SeqIO.parse(io.StringIO(archive.read(files[0]).decode()), 'genbank'))
                chromosomes = [r for r in records if len(r) > 1_000_000 and not any('plasmid' in f.qualifiers for f in r.features if f.type == 'source')]
                if len(chromosomes) != 1:
                    raise ValueError(f'Expected one chromosome: {accession}')
                record = chromosomes[0]
                excluded = [{'accession': r.id, 'bases': len(r)} for r in records if r.id != record.id]
                out = io.StringIO(); SeqIO.write(record, out, 'genbank'); gbk = out.getvalue().encode()
                (DEST / filename).write_bytes(gzip.compress(gbk, mtime=0))
                time.sleep(.4)
            if record.annotations.get('topology') != 'circular' or not record.annotations['organism'].startswith('Helicobacter pylori'):
                raise ValueError(f'Unexpected organism or topology: {accession}')
            if sum(f.type == 'CDS' for f in record.features) < 1000:
                raise ValueError(f'Missing chromosome annotations: {accession}')
            fasta = WORK / f'{gid:02d}-{accession}.fasta'
            SeqIO.write(record, fasta, 'fasta')
            manifest['genomes'].append({'id': gid, 'strain': strain, 'accession': accession,
                'organism': record.annotations['organism'], 'name': f'H. pylori {strain} ({record.id})',
                'chromosome': record.id, 'bases': len(record), 'topology': 'circular',
                'annotations': filename, 'genbank_sha256': hashlib.sha256(gbk).hexdigest(),
                'sequence_sha256': hashlib.sha256(str(record.seq).upper().encode()).hexdigest(),
                'download_url': url + '?include_annotation_type=GENOME_GBFF',
                'url': f'https://www.ncbi.nlm.nih.gov/datasets/genome/{accession}/',
                'excluded_records': excluded, 'input_file': fasta.name, 'features': len(record.features)})
            (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            print(f'Saved {strain}: {len(record):,} bases', flush=True)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--align', action='store_true')
    parser.add_argument('--aligner', default=str(DEST.parents[1] / 'native/bin/progressiveMauve'))
    args = parser.parse_args()
    manifest = prepare()
    if args.align:
        builder.DEST, builder.WORK = DEST, WORK
        builder.align(manifest, args.aligner)
