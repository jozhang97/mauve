"""GenBank annotations in the same 1-based coordinate system as XMFA."""
from io import StringIO
import warnings

from Bio import BiopythonParserWarning, SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import ExactPosition


def parse_genbank(text, members, concatenate=False):
    # Fail on parser warnings instead of silently dropping malformed locations.
    with warnings.catch_warnings():
        warnings.simplefilter('error', BiopythonParserWarning)
        try:
            records = list(SeqIO.parse(StringIO(text), 'genbank'))
        except (ValueError, BiopythonParserWarning) as exc:
            raise ValueError(f'Invalid GenBank file: {exc}') from exc
    if not records:
        raise ValueError('No GenBank records found.')
    if len(records) > 1 and not concatenate:
        raise ValueError('This file contains multiple records. Enable concatenation only if the alignment uses these records in file order.')
    try:
        sequence = ''.join(str(record.seq).upper() for record in records)
    except ValueError as exc:
        raise ValueError('GenBank records must include their DNA sequence for coordinate verification.') from exc
    comparable = 0
    for member in members:
        if member['end'] > len(sequence):
            raise ValueError('GenBank sequence is shorter than the aligned coordinates for this genome.')
        source = sequence[member['start'] - 1:member['end']]
        if member['strand'] == '-':
            source = str(Seq(source).reverse_complement())
        for actual, expected in zip(member['sequence'].replace('-', ''), source):
            if actual in 'ACGT' and expected in 'ACGT':
                comparable += 1
                if actual != expected:
                    raise ValueError('GenBank sequence does not match the selected genome at aligned coordinates. Check the genome and record order.')
    if not comparable:
        raise ValueError('No unambiguous aligned bases are available to verify this GenBank sequence.')
    features, contigs, offset = [], [], 0
    for record in records:
        contigs.append({'name': record.id, 'start': offset + 1, 'end': offset + len(record),
                        'topology': record.annotations.get('topology', 'unknown')})
        for feature in record.features:
            if feature.type == 'source':
                continue
            if feature.location is None:
                raise ValueError('A feature has an unsupported or missing location.')
            parts = []
            for part in feature.location.parts:
                if part.ref or part.ref_db:
                    raise ValueError('Remote feature locations are not supported.')
                try:
                    start, end = int(part.start), int(part.end)
                except (TypeError, ValueError) as exc:
                    raise ValueError('A feature has unknown coordinates that cannot be displayed.') from exc
                if not 0 <= start < end <= len(record):
                    raise ValueError('A feature location lies outside its record or has zero length.')
                parts.append({'start': offset + start + 1, 'end': offset + end,
                              'strand': '+' if part.strand == 1 else '-' if part.strand == -1 else '.',
                              'fuzzy': not isinstance(part.start, ExactPosition) or not isinstance(part.end, ExactPosition)})
            qualifiers = feature.qualifiers
            def value(key):
                return '; '.join(qualifiers.get(key, []))
            name = value('gene') or value('locus_tag') or value('label') or feature.type
            features.append({'name': name, 'type': feature.type, 'locus_tag': value('locus_tag'),
                             'product': value('product'), 'note': value('note'), 'record': record.id,
                             'pseudo': 'pseudo' in qualifiers or 'pseudogene' in qualifiers,
                             'experiment': value('experiment'), 'inference': value('inference'),
                             'start': min(p['start'] for p in parts), 'end': max(p['end'] for p in parts),
                             'strand': '+' if feature.location.strand == 1 else '-' if feature.location.strand == -1 else '.',
                             'location': str(feature.location), 'parts': parts})
        offset += len(record)
    if not features:
        raise ValueError('No non-source annotations were found in this GenBank file.')
    return {'features': features, 'records': contigs, 'length': len(sequence), 'verified_bases': comparable}
