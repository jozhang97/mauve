"""Reproduce the frozen E. coli demo from its sampled-strain manifest.

A fresh sample uses the NCBI current, annotated, complete RefSeq E. coli pool,
one representative assembly per named strain. Only a single circular chromosome
is retained; plasmids are excluded. The random seed and eligible pool are saved.
Run with web/.venv/bin/python web/demo/build_ecoli.py --sample to prepare inputs,
then use --align to create the compressed precomputed alignment. Without --sample,
the saved sample is reused. --finalize packages an already completed alignment.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import random
import secrets
import subprocess
import time
from datetime import datetime, timezone
import zipfile

import httpx
from Bio import SeqIO

ROOT = Path(__file__).resolve().parent
DEST = ROOT / 'ecoli'
WORK = Path('/tmp/mauve-ecoli')
BASE = 'https://api.ncbi.nlm.nih.gov/datasets/v2'
PARAMS = {'filters.assembly_level': 'complete_genome', 'filters.assembly_source': 'refseq',
          'filters.has_annotation': 'true', 'filters.assembly_version': 'current', 'page_size': 1000}


def fetch(client, url, **kwargs):
    for attempt in range(5):
        try:
            response = client.get(url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPError:
            if attempt == 4:
                raise
            time.sleep(min(10, 2 ** attempt))


def sample(client):
    reports, token = [], ''
    while True:
        params = {**PARAMS, **({'page_token': token} if token else {})}
        data = fetch(client, f'{BASE}/genome/taxon/562/dataset_report', params=params).json()
        reports.extend(data.get('reports', []))
        print(f'Metadata {len(reports)}/{data.get("total_count")}', flush=True)
        token = data.get('next_page_token')
        if not token:
            break
        time.sleep(.4)
    by_strain = {}
    for report in sorted(reports, key=lambda r: r['accession']):
        org, info, stats = report['organism'], report['assembly_info'], report['assembly_stats']
        strain = org.get('infraspecific_names', {}).get('strain', '').strip()
        if not strain or strain.casefold() in {'unknown', 'not provided', 'missing', 'na'}:
            continue
        if not org['organism_name'].startswith('Escherichia coli') or info['assembly_level'] != 'Complete Genome':
            continue
        if stats.get('total_number_of_chromosomes') != 1 or not report.get('annotation_info'):
            continue
        by_strain.setdefault(strain.casefold(), {'accession': report['accession'], 'strain': strain,
            'organism': org['organism_name'], 'assembly_name': info['assembly_name'],
            'annotation': report['annotation_info'].get('name'), 'annotation_date': report['annotation_info'].get('release_date'),
            'url': f'https://www.ncbi.nlm.nih.gov/datasets/genome/{report["accession"]}/'})
    pool = list(by_strain.values())
    seed = secrets.randbits(64)
    (DEST / 'sampling-pool.json.gz').write_bytes(gzip.compress(json.dumps(pool, indent=2).encode(), mtime=0))
    random.Random(seed).shuffle(pool)
    return {'id': 'ecoli-eight-v1', 'name': 'E. coli · 8-strain demo', 'created': datetime.now(timezone.utc).isoformat(),
        'seed': str(seed), 'sampling': 'Uniform random permutation of named strains; first 8 with a usable complete circular annotated chromosome. One representative per strain, lowest accession in sorted current RefSeq pool. Plasmids excluded.',
        'query': f'{BASE}/genome/taxon/562/dataset_report', 'query_parameters': PARAMS,
        'reported_assemblies': len(reports), 'eligible_strains': len(pool), 'rejected': [], 'genomes': []}, pool


def prepare(client, manifest, pool):
    for item in pool:
        gid = len(manifest['genomes']) + 1
        accession = item['accession']
        url = f'{BASE}/genome/accession/{accession}/download'
        print(f'Downloading {gid}/8: {accession} {item["strain"]}', flush=True)
        raw = fetch(client, url, params={'include_annotation_type': 'GENOME_GBFF'}).content
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = [p for p in archive.namelist() if p.startswith(f'ncbi_dataset/data/{accession}/') and p.endswith('.gbff')]
            if len(files) != 1:
                raise ValueError(f'Expected one GenBank file for {accession}: {files}')
            records = list(SeqIO.parse(io.StringIO(archive.read(files[0]).decode()), 'genbank'))
        chromosomes = [r for r in records if len(r) > 1_000_000 and not any('plasmid' in f.qualifiers for f in r.features if f.type == 'source')]
        if len(chromosomes) != 1 or chromosomes[0].annotations.get('topology') != 'circular' or not any(f.type == 'CDS' for f in chromosomes[0].features):
            manifest['rejected'].append({'accession': accession, 'reason': 'Not one usable circular annotated chromosome'})
            continue
        r = chromosomes[0]
        name = f'E. coli {item["strain"]} ({r.id})'
        out = io.StringIO(); SeqIO.write(r, out, 'genbank'); gbk = out.getvalue().encode()
        filename = f'{accession}.gbk.gz'
        (DEST / filename).write_bytes(gzip.compress(gbk, mtime=0))
        fasta = WORK / f'{gid:02d}-{accession}.fasta'
        SeqIO.write(r, fasta, 'fasta')
        entry = {**item, 'id': gid, 'name': name, 'chromosome': r.id, 'bases': len(r), 'topology': 'circular',
            'annotations': filename, 'genbank_sha256': hashlib.sha256(gbk).hexdigest(),
            'sequence_sha256': hashlib.sha256(str(r.seq).upper().encode()).hexdigest(),
            'download_url': url + '?include_annotation_type=GENOME_GBFF',
            'excluded_records': [{'accession': x.id, 'bases': len(x)} for x in records if x.id != r.id],
            'input_file': fasta.name, 'features': len(r.features)}
        manifest['genomes'].append(entry)
        (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        print(f'Saved {r.id}: {len(r):,} bases, {len(r.features):,} features', flush=True)
        if gid == 8:
            break
        time.sleep(.4)
    if len(manifest['genomes']) != 8:
        raise ValueError('Could not obtain eight eligible chromosomes')


def finalize(manifest):
    raw = (WORK / 'alignment.xmfa').read_bytes()
    if not raw:
        raise ValueError('The alignment is empty or still running')
    raw = raw.replace((str(WORK) + '/').encode(), b'')
    destination = DEST / 'alignment.xmfa.gz'
    destination.write_bytes(gzip.compress(raw, mtime=0))
    manifest['seed'] = str(manifest['seed'])
    for genome in manifest['genomes']:
        genome['input_file'] = Path(genome.pop('fasta', genome.get('input_file', ''))).name
    alignment = manifest['alignment']
    alignment['command'] = ['progressiveMauve', '--output=alignment.xmfa', '--output-guide-tree=guide.tree', '--backbone-output=backbone.tsv', *[g['input_file'] for g in manifest['genomes']]]
    alignment.update({'file': destination.name, 'sha256': hashlib.sha256(raw).hexdigest(),
                      'bytes': len(raw), 'compressed_bytes': destination.stat().st_size,
                      'blocks': sum(line == b'=' for line in raw.splitlines())})
    manifest['total_bases'] = sum(g['bases'] for g in manifest['genomes'])
    manifest['download_bytes'] = sum(p.stat().st_size for p in DEST.glob('*.gz') if p.name != 'sampling-pool.json.gz')
    (DEST / 'guide.tree').write_bytes((WORK / 'guide.tree').read_bytes())
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Packaged {alignment["blocks"]} blocks; {manifest["download_bytes"] / 1024**2:.1f} MiB compressed demo', flush=True)


def align(manifest, executable):
    executable = Path(executable).resolve()
    command = [str(executable), '--output=alignment.xmfa', '--output-guide-tree=guide.tree', '--backbone-output=backbone.tsv', *[g['input_file'] for g in manifest['genomes']]]
    manifest['alignment'] = {'file': 'alignment.xmfa.gz', 'command': command,
        'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
        'engine': 'progressiveMauve native', 'parameters': 'Default full progressive alignment, including gapped alignment and refinement'}
    with (WORK / 'alignment.log').open('w') as log:
        subprocess.run(command, cwd=WORK, stdout=log, stderr=subprocess.STDOUT, check=True)
    finalize(manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample', action='store_true', help='Draw a new random sample and overwrite the demo manifest')
    parser.add_argument('--align', action='store_true', help='Align the prepared chromosome FASTAs and package the demo')
    parser.add_argument('--aligner', default=str(ROOT.parent / 'native/bin/progressiveMauve'))
    parser.add_argument('--finalize', action='store_true', help='Package the completed alignment without rerunning it')
    args = parser.parse_args()
    WORK.mkdir(exist_ok=True); DEST.mkdir(exist_ok=True)
    if args.finalize:
        finalize(json.loads((DEST / 'manifest.json').read_text()))
        raise SystemExit(0)
    with httpx.Client(timeout=180, follow_redirects=True, headers={'User-Agent': 'MauveExplorer demo builder'}) as client:
        if args.sample:
            manifest, pool = sample(client)
        else:
            previous = json.loads((DEST / 'manifest.json').read_text())
            pool = previous['genomes']; manifest = {**previous, 'genomes': []}
        if not args.align or args.sample or not all((WORK / g.get('input_file', '')).is_file() for g in pool):
            prepare(client, manifest, pool)
        else:
            manifest['genomes'] = pool
        if args.align:
            align(manifest, args.aligner)
