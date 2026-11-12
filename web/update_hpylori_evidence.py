"""Build H. pylori evidence from frozen assay calls and official DoriC shards.

web/.venv/bin/python web/update_hpylori_evidence.py --reference AE000511.1.gbk \
    --doric /path/to/shards
Generate shards with web/update_doric.py. Original GenBank/demo inputs stay intact.
"""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path

from Bio import SeqIO
from Bio.SeqFeature import ExactPosition

ROOT = Path(__file__).resolve().parent
TABLE = ROOT / 'data/essentiality/chalker-2001-hpylori.tsv'
PUBLICATION = 'https://doi.org/10.1128/JB.183.4.1259-1268.2001'
ORIGIN_PUBLICATION = 'https://doi.org/10.1093/nar/gks742'


def essentiality(reference):
    record = SeqIO.read(reference, 'genbank')
    if record.id != 'AE000511.1':
        raise ValueError('Expected original 26695 reference AE000511.1 with HP locus tags')
    features = defaultdict(list)
    for f in record.features:
        if f.type == 'CDS':
            for tag in f.qualifiers.get('locus_tag', []):
                features[tag.replace('_', '')].append(f)
    rows = list(csv.DictReader(TABLE.open(), delimiter='\t'))
    if len(rows) != 45 or len({r['locus_tag'] for r in rows}) != 45:
        raise ValueError('Expected 45 unique tested loci')
    sequences = defaultdict(list)
    counts = Counter()
    for row in rows:
        if row['status'] not in ('essential', 'nonessential'):
            raise ValueError('Unknown assay call')
        matches = features[row['locus_tag']]
        if len(matches) != 1:
            raise ValueError(f'Ambiguous or missing locus: {row}')
        f = matches[0]
        if 'pseudo' in f.qualifiers or any(not isinstance(p.start, ExactPosition) or not isinstance(p.end, ExactPosition) for p in f.location.parts):
            raise ValueError(f'Unusable locus: {row}')
        sequence = str(f.extract(record.seq)).upper()
        if set(sequence) - set('ACGT'):
            counts['ambiguous_reference_sequence'] += 1
            continue
        sequences[hashlib.sha256(sequence.encode()).hexdigest()].append(row)
        counts[row['status']] += 1
    return {'schema_version': 1, 'source': {
        'id': 'chalker-2001-hpylori', 'title': 'Chalker et al. (2001), Table 1: 45 targeted genes',
        'publication': PUBLICATION, 'table_url': 'https://pmc.ncbi.nlm.nih.gov/articles/PMC94999/#T1',
        'strain': 'Helicobacter pylori 26695', 'reference': record.id,
        'method': 'Targeted allelic replacement mutagenesis; 45 selected genes, not a genome-wide essentiality screen',
        'conditions': 'In vitro growth at 37 C under microaerobic conditions on Columbia agar with 5% horse blood. Nutritional supplementation was tested for selected genes. Calls apply to this experiment; untested genes remain unknown.',
        'license': 'Factual locus identifiers and assay calls transcribed from Table 1; article copyright ASM (2001).',
        'table_sha256': hashlib.sha256(TABLE.read_bytes()).hexdigest(),
        'reference_sha256': hashlib.sha256(str(record.seq).upper().encode()).hexdigest(),
        'mapping': 'Paper HP number to unique original reference HP locus tag; exact complete CDS SHA-256 at runtime. Sequence variants remain unknown.',
        'input_rows': len(rows), 'counts': dict(counts)}, 'sequences': dict(sorted(sequences.items()))}


def origins(shards):
    target = ROOT / 'mauve_web/static/doric-demo.json'
    snapshot = json.loads(target.read_text())
    manifest = json.loads((ROOT / 'demo/hpylori/manifest.json').read_text())
    for g in manifest['genomes']:
        record = SeqIO.read(io.StringIO(gzip.decompress((ROOT / 'demo/hpylori' / g['annotations']).read_bytes()).decode()), 'genbank')
        accession = record.id
        data = json.loads((shards / (hashlib.sha256(accession.encode()).hexdigest()[:2] + '.json')).read_text())
        matches = []
        for r in data['records'].get(accession, []):
            sequence = str(record.seq[r['start'] - 1:r['end']]).upper()
            if r['length'] == len(record) and sequence == r['sequence']:
                matches.append(r)
        dna = [f for f in record.features if f.type == 'CDS' and f.qualifiers.get('gene') == ['dnaA']]
        if len(dna) != 1:
            raise ValueError(f'Expected one dnaA: {accession}')
        gene = dna[0]
        # oriC1 is immediately upstream of dnaA in biological orientation.
        upstream = [r for r in matches if (r['end'] == int(gene.location.start) if gene.location.strand == 1 else r['start'] == int(gene.location.end) + 1)]
        if len(upstream) != 1:
            raise ValueError(f'Expected one sequence-verified upstream oriC1: {accession}')
        selected = upstream[0]
        snapshot['records'][accession] = [{
            'id': selected['id'], 'start': selected['start'], 'end': selected['end'],
            'length': len(record), 'sha256': g['sequence_sha256'],
            'anchor': 'oriC1 region start', 'publication': ORIGIN_PUBLICATION,
            'note': 'Bipartite H. pylori origin. Coordinate anchor is the start of the DoriC oriC1 region upstream of dnaA, not an experimentally resolved initiation nucleotide. DNA unwinding occurs in oriC2 downstream of dnaA.',
            'regions': [{k: r[k] for k in ('id', 'start', 'end')} for r in matches],
            'source': data.get('source', 'https://tubic.org/doric/'),
        }]
    snapshot['hpylori_policy'] = {'publication': ORIGIN_PUBLICATION,
        'selection': 'One upstream oriC1 region adjacent to dnaA, exact accession, length, whole-chromosome checksum and region sequence verified. Other matching DoriC regions retained as provenance; no arbitrary selection among unrelated origins.'}
    target.write_text(json.dumps(snapshot, indent=2) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--doric', type=Path, required=True)
    args = p.parse_args()
    snapshot = essentiality(args.reference)
    (ROOT / 'mauve_web/static/essentiality-hpylori.json').write_text(json.dumps(snapshot, indent=2) + '\n')
    origins(args.doric)
    print(snapshot['source']['counts'])
