"""GenBank annotations in the same 1-based coordinate system as XMFA."""
from io import StringIO
import hashlib
import json
from pathlib import Path
import warnings

from Bio import BiopythonParserWarning, SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import ExactPosition, SimpleLocation, CompoundLocation


def parse_genbank(text, members, concatenate=False, rotation=0):
    # Fail on parser warnings instead of silently dropping malformed locations.
    with warnings.catch_warnings():
        warnings.simplefilter('error', BiopythonParserWarning)
        try:
            records = list(SeqIO.parse(StringIO(text), 'genbank'))
        except (ValueError, BiopythonParserWarning) as exc:
            raise ValueError(f'Invalid GenBank file: {exc}') from exc
    if not records:
        raise ValueError('No GenBank records found.')
    if rotation:
        if len(records) != 1:
            raise ValueError('Rotation requires a single chromosome.')
        record = records[0]
        n = len(record)
        for feature in record.features:
            parts = []
            for part in feature.location.parts:
                if part.ref or part.ref_db:
                    raise ValueError('Remote feature locations are not supported.')
                if part.start < rotation < part.end:
                    split = [SimpleLocation(part.start + n - rotation, n, strand=part.strand),
                             SimpleLocation(0, part.end - rotation, strand=part.strand)]
                    parts.extend(split[::-1] if part.strand == -1 else split)
                else:
                    shift = -rotation if part.start >= rotation else n - rotation
                    parts.append(part + shift)
            feature.location = parts[0] if len(parts) == 1 else CompoundLocation(parts)
        record.seq = record.seq[rotation:] + record.seq[:rotation]
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
                             'sequence_sha256': hashlib.sha256(str(feature.extract(record.seq)).upper().encode()).hexdigest()
                             if feature.type == 'CDS' and not any(p['fuzzy'] for p in parts) else '',
                             'start': min(p['start'] for p in parts), 'end': max(p['end'] for p in parts),
                             'strand': '+' if feature.location.strand == 1 else '-' if feature.location.strand == -1 else '.',
                             'location': str(feature.location), 'parts': parts})
        offset += len(record)
    if not features:
        raise ValueError('No non-source annotations were found in this GenBank file.')
    for contig, record in zip(contigs, records):
        origins = [f for f in features if f['record'] == record.id and f['type'] == 'rep_origin']
        if len(origins) == 1 and not any(p['fuzzy'] for p in origins[0]['parts']):
            parts = origins[0]['parts']
            contig['replication_origin'] = (parts[-1] if parts[0]['strand'] == '-' else parts[0])['start']
            original = next(f for f in record.features if f.type == 'rep_origin')
            contig['replication_direction'] = ''.join(original.qualifiers.get('direction', []))
        elif not origins:
            snapshot = json.loads((Path(__file__).parent / 'static/doric-demo.json').read_text())
            digest = hashlib.sha256(str(record.seq).upper().encode()).hexdigest()
            matches = [m for m in snapshot['records'].get(record.id, [])
                       if m['length'] == len(record) and m.get('sha256') == digest]
            if len(matches) == 1:
                contig['replication_origin'] = contig['start'] + matches[0]['start'] - 1
                anchor = matches[0].get('anchor')
                contig['replication_origin_source'] = f'DoriC (sequence verified; {anchor})' if anchor else 'DoriC (sequence verified)'
                contig['replication_origin_note'] = matches[0].get('note', '')
                contig['replication_origin_regions'] = matches[0].get('regions', [])
                contig['replication_origin_publication'] = matches[0].get('publication', '')
        window = max(1, (len(record) + 199) // 200)
        contig['gc_skew'] = []
        dna = str(record.seq).upper()
        for start in range(0, len(record), window):
            segment = dna[start:start + window]
            g, c = segment.count('G'), segment.count('C')
            contig['gc_skew'].append({'start': contig['start'] + start,
                                      'end': contig['start'] + start + len(segment) - 1,
                                      'value': (g - c) / (g + c) if g + c else None})
    return {'features': features, 'records': contigs, 'length': len(sequence), 'verified_bases': comparable}
