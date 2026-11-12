"""Build the bundled Goodall/Galaxy snapshot using CP009273.1 GenBank CDS.

Run: web/.venv/bin/python web/update_essentiality.py --reference /path/CP009273.1.gbk
Reference download: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore&id=CP009273.1&rettype=gbwithparts&retmode=text
The frozen TSV is Galaxy Training Network's transcription of Goodall et al.
Its library/condition subset is not specified; do not present it as all conditions.
"""
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from Bio import SeqIO
from Bio.SeqFeature import ExactPosition

ROOT = Path(__file__).resolve().parent
TABLE = ROOT / 'data/essentiality/goodall-2018-galaxy.tsv'
OUTPUT = ROOT / 'mauve_web/static/essentiality-ecoli.json'


def build(reference, table=TABLE):
    record = SeqIO.read(reference, 'genbank')
    if record.id != 'CP009273.1':
        raise ValueError('Expected E. coli BW25113 reference CP009273.1')
    rows = list(csv.reader(Path(table).read_text().splitlines(), delimiter='\t'))
    names = defaultdict(dict)
    for f in record.features:
        if f.type != 'CDS' or 'pseudo' in f.qualifiers or 'pseudogene' in f.qualifiers:
            continue
        if any(not isinstance(p.start, ExactPosition) or not isinstance(p.end, ExactPosition) for p in f.location.parts):
            continue
        tag = f.qualifiers['locus_tag'][0]
        for name in f.qualifiers.get('gene', []) + [n.strip() for v in f.qualifiers.get('gene_synonym', []) for n in v.split(';')]:
            names[name][tag] = f
    occurrences = Counter(row[0] for row in rows)
    sequences = defaultdict(list)
    counts = Counter()
    for row in rows:
        if len(row) != 6 or row[3:] not in (['1', '0', '0'], ['0', '1', '0'], ['0', '0', '1']):
            raise ValueError(f'Invalid essentiality row: {row}')
        gene = row[0]
        if occurrences[gene] != 1 or len(names[gene]) != 1:
            counts['unmapped_or_ambiguous'] += 1
            continue
        tag, feature = next(iter(names[gene].items()))
        sequence = str(feature.extract(record.seq)).upper()
        if set(sequence) - set('ACGT'):
            counts['unmapped_or_ambiguous'] += 1
            continue
        status = ['essential', 'nonessential', 'unclear'][row[3:].index('1')]
        digest = hashlib.sha256(sequence.encode()).hexdigest()
        sequences[digest].append({'gene': gene, 'locus_tag': tag, 'status': status})
        counts[status] += 1
    return {'schema_version': 1, 'source': {
        'id': 'goodall-2018-galaxy', 'title': 'Goodall et al. (2018), Galaxy Training Network transcription',
        'publication': 'https://doi.org/10.1128/mBio.02096-17',
        'table_url': 'https://zenodo.org/records/3382053/files/inline-supplementary-material-7.tsv',
        'documentation': 'https://training.galaxyproject.org/training-material/topics/assembly/tutorials/ecoli_comparison/tutorial.html#are-any-of-these-genes-essential',
        'strain': 'Escherichia coli K-12 BW25113', 'reference': record.id,
        'method': 'TraDIS transposon insertion sequencing',
        'conditions': 'See study; the transcribed TSV does not specify the library/condition subset.',
        'license': 'CC BY 4.0 (Goodall et al.)',
        'table_sha256': hashlib.sha256(Path(table).read_bytes()).hexdigest(),
        'reference_sha256': hashlib.sha256(str(record.seq).upper().encode()).hexdigest(),
        'mapping': 'Unique table gene name to unique reference CDS gene/synonym; exact full CDS SHA-256 at runtime.',
        'input_rows': len(rows), 'counts': dict(counts)}, 'sequences': dict(sorted(sequences.items()))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    args = parser.parse_args()
    snapshot = build(args.reference)
    OUTPUT.write_text(json.dumps(snapshot, indent=2) + '\n')
    print(json.dumps(snapshot['source']['counts']))
