"""Reproduce B. subtilis demo selection using canonical circular 21-mer sketches.

Requires NumPy, Biopython, httpx, and DoriC shards from web/update_doric.py.
Run: web/.venv/bin/python web/demo/measure_bsubtilis_diversity.py --doric /path/to/shards
Downloads are cached outside the repository. This estimates k-mer Jaccard
similarity, not ANI, a phylogeny, or the number of structural rearrangements.
"""
import argparse
import hashlib
import io
import itertools
import json
from pathlib import Path
import statistics
import time
import zipfile

import httpx
import numpy as np
from Bio import SeqIO

import build_ecoli as builder

CANDIDATES = [
    ('XF-1', 'GCF_000338735.1'), ('BAB-1', 'GCF_000349795.1'),
    ('UD1022', 'GCF_001015095.1'), ('OH131.1', 'GCF_000706705.1'),
    ('HJ5', 'GCF_000973605.1'), ('BSD-2', 'GCF_001465815.1'),
    ('SG6', 'GCF_000782835.1'), ('TO-A', 'GCF_000737405.1'),
    ('168', 'GCF_000009045.1'), ('NCIB 3610', 'GCF_002055965.1'),
    ('PY79', 'GCF_000497485.1'), ('QB928', 'GCF_000293765.1'),
    ('BSn5', 'GCF_000186745.1'), ('RO-NN-1', 'GCF_000227485.1'),
]
PREVIOUS = ['168', 'NCIB 3610', 'PY79', 'QB928', 'BSn5', 'RO-NN-1']
EXCLUDED = ['NCIB 3610', 'PY79', 'QB928']


def sketch(sequence):
    """4096 smallest distinct SplitMix64 hashes of canonical circular 21-mers."""
    table = np.full(256, 4, dtype=np.uint64)
    for i, base in enumerate(b'ACGT'):
        table[base] = i
    bases = table[np.frombuffer(sequence.encode(), dtype=np.uint8)]
    forward = np.zeros(len(bases), dtype=np.uint64)
    reverse = forward.copy()
    valid = np.ones(len(bases), dtype=bool)
    for j in range(21):
        value = np.roll(bases, -j)
        valid &= value < 4
        forward = (forward << np.uint64(2)) | value
        reverse |= (3 - value) << np.uint64(2 * j)
    hashes = np.minimum(forward, reverse)[valid]
    hashes = (hashes ^ (hashes >> np.uint64(30))) * np.uint64(0xbf58476d1ce4e5b9)
    hashes = (hashes ^ (hashes >> np.uint64(27))) * np.uint64(0x94d049bb133111eb)
    hashes ^= hashes >> np.uint64(31)
    hashes = np.unique(hashes)
    return set(map(int, np.partition(hashes, 4095)[:4096]))


def similarity(left, right):
    union = sorted(left | right)[:4096]
    return sum(h in left and h in right for h in union) / len(union)


def verified_origin(record, shards):
    sequence = str(record.seq).upper()
    data = json.loads((shards / (hashlib.sha256(record.id.encode()).hexdigest()[:2] + '.json')).read_text())
    dna = [f for f in record.features if f.type == 'CDS' and f.qualifiers.get('gene') == ['dnaA']]
    if len(dna) != 1 or dna[0].location.strand not in (-1, 1):
        return False
    matches = []
    for region in data['records'].get(record.id, []):
        if region['length'] != len(record):
            continue
        for start in (region['start'], region['start'] + 1):
            end = region['end']
            actual = sequence[start - 1:end] if start <= end else sequence[start - 1:] + sequence[:end]
            downstream = start == int(dna[0].location.end) + 1 if dna[0].location.strand == 1 else end == int(dna[0].location.start)
            if actual == region['sequence'] and downstream:
                matches.append(start)
    return len(matches) == 1


def measure(work, shards):
    work.mkdir(parents=True, exist_ok=True)
    genomes, sketches = [], {}
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        for strain, accession in CANDIDATES:
            path = work / f'{accession}.gbff'
            if not path.exists():
                url = f'{builder.BASE}/genome/accession/{accession}/download'
                print(f'Downloading {strain}: {accession}', flush=True)
                raw = builder.fetch(client, url, params={'include_annotation_type': 'GENOME_GBFF'}).content
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    filename, = [p for p in archive.namelist() if p.startswith(f'ncbi_dataset/data/{accession}/') and p.endswith('.gbff')]
                    path.write_bytes(archive.read(filename))
                time.sleep(.4)
            chromosomes = [r for r in SeqIO.parse(path, 'genbank') if len(r) > 1_000_000 and not any(
                'plasmid' in f.qualifiers for f in r.features if f.type == 'source')]
            record, = chromosomes
            if (record.annotations.get('topology') != 'circular' or
                    not record.annotations['organism'].startswith('Bacillus subtilis') or
                    not verified_origin(record, shards)):
                raise ValueError(f'Candidate failed chromosome/origin validation: {strain}')
            sequence = str(record.seq).upper()
            genomes.append({'strain': strain, 'accession': accession, 'chromosome': record.id,
                            'sequence_sha256': hashlib.sha256(sequence.encode()).hexdigest()})
            sketches[strain] = sketch(sequence)
            print(f'Sketched {strain}', flush=True)
    matrix = {a: {b: round(similarity(sketches[a], sketches[b]), 6) for b in sketches} for a in sketches}
    selected = ['168']
    while len(selected) < 6:
        remaining = [s for s in sketches if s not in selected and s not in EXCLUDED]
        selected.append(min(remaining, key=lambda s: max(matrix[s][t] for t in selected)))
    def summary(panel):
        values = [matrix[a][b] for a, b in itertools.combinations(panel, 2)]
        return {'median_pairwise_similarity': statistics.median(values), 'maximum_pairwise_similarity': max(values)}
    return {
        'method': 'Bottom-4096 union sketch estimate of canonical circular 21-mer Jaccard similarity using SplitMix64; maximin selection anchored on 168, excluding NCIB 3610, PY79 and QB928 from selection. This is not ANI, a phylogeny, or a rearrangement count.',
        'scope': 'Curated candidate pool of 14 pinned complete annotated B. subtilis chromosomes; all require sequence-verified downstream DoriC oriC2. Not an exhaustive species-wide search.',
        'k': 21, 'sketch_size': 4096, 'candidates': genomes, 'similarity': matrix,
        'excluded_from_selection': EXCLUDED, 'selected': selected, 'previous': PREVIOUS,
        'comparison': {'previous': summary(PREVIOUS), 'selected': summary(selected)},
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--doric', type=Path, required=True)
    parser.add_argument('--work', type=Path, default=Path('/tmp/mauve-bsubtilis-candidates'))
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'bsubtilis/diversity.json')
    args = parser.parse_args()
    result = measure(args.work, args.doric)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(result['selected'])
    print(result['comparison'])
