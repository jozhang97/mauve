"""XMFA parsing. All genomic coordinates are 1-based, inclusive.

Reverse-strand records already contain reverse-complemented aligned bases;
retain those bases and count coordinates downwards when inspecting columns.
"""
import re
import io
import numpy as np

# Bound temporary arrays even when a caller requests a single profile window.
SCAN_CHUNK = 65536
CANONICAL = np.zeros(256, dtype=np.bool_)
CANONICAL[list(b'ACGT')] = True

HEADER = re.compile(r'^>\s*(\d+):(\d+)-(\d+)\s+([+-])(?:\s+(.*))?$')
META = re.compile(r'^#Sequence(\d+)File\s+(.+)$')
BASES = re.compile(r'^[ACGTRYSWKMBDHVNacgtryswkmbdhvn-]+$')


def basename(value):
    return value.replace('\\', '/').rsplit('/', 1)[-1]


def parse_xmfa(text):
    genomes = {}
    blocks = list(iter_xmfa(io.StringIO(text), genomes))
    return {'genomes': sorted((g for g in genomes.values() if g['extent']), key=lambda g: g['id']), 'blocks': blocks}


def iter_xmfa(lines, genomes):
    """Validate and yield one block at a time, populating genome metadata."""
    members = []
    block_count = 0
    current = None

    def finish_record():
        nonlocal current
        if current is None:
            return
        sequence = ''.join(current.pop('parts')).upper()
        start, end = current['start'], current['end']
        if start == end == 0:
            if sequence.replace('-', ''):
                raise ValueError('Absent (0-0) records must contain only gaps.')
            current = None
            return
        if start < 1 or end < start:
            raise ValueError('Coordinates must be positive and start must not exceed end.')
        if len(sequence.replace('-', '')) != end - start + 1:
            raise ValueError(f"Sequence {current['genome_id']}: coordinate span does not match ungapped bases.")
        if any(m['genome_id'] == current['genome_id'] for m in members):
            raise ValueError('A block contains the same sequence more than once.')
        current['sequence'] = sequence
        gid = current['genome_id']
        genomes[gid]['extent'] = max(genomes[gid]['extent'], end)
        members.append(current)
        current = None

    def finish_block():
        nonlocal block_count
        finish_record()
        if not members:
            return
        lengths = {len(m['sequence']) for m in members}
        if len(lengths) != 1:
            raise ValueError('Aligned sequences within a block must have equal column counts.')
        block_count += 1
        block = {'id': block_count, 'columns': lengths.pop(), 'members': members.copy()}
        members.clear()
        return block

    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        meta = META.match(line)
        if meta:
            gid = int(meta[1])
            genomes.setdefault(gid, {'id': gid, 'name': basename(meta[2]), 'extent': 0})
        elif line.startswith('#'):
            continue
        elif line.startswith('>'):
            finish_record()
            match = HEADER.match(line)
            if not match:
                raise ValueError(f'Invalid XMFA sequence header at line {number}.')
            gid, start, end = map(int, match.group(1, 2, 3))
            if gid < 1:
                raise ValueError('Sequence IDs must be positive.')
            genomes.setdefault(gid, {'id': gid, 'name': basename(match[5] or f'Sequence {gid}'), 'extent': 0})
            current = {'genome_id': gid, 'start': start, 'end': end, 'strand': match[4], 'parts': []}
        elif line.startswith('='):
            block = finish_block()
            if block is not None:
                yield block
        elif current is not None and BASES.fullmatch(line):
            current['parts'].append(line)
        else:
            raise ValueError(f'Unexpected content at line {number}; expected XMFA aligned DNA.')
    block = finish_block()
    if block is not None:
        yield block
    if not block_count:
        raise ValueError('No aligned sequence blocks found. Upload an XMFA or Mauve .alignment file.')


def column_slice(member, offset, limit):
    sequence = member['sequence']
    preceding = offset - sequence.count('-', 0, offset)
    step = 1 if member['strand'] == '+' else -1
    coordinate = (member['start'] if step == 1 else member['end']) + step * preceding
    positions = []
    for base in sequence[offset:offset + limit]:
        positions.append(None if base == '-' else coordinate)
        if base != '-':
            coordinate += step
    return {**{k: v for k, v in member.items() if k != 'sequence'},
            'bases': sequence[offset:offset + limit], 'positions': positions}


def identity_profile(block, reference_id, bins=100):
    """Canonical-pair identity in alignment-column windows, placed on native coordinates.

    Gaps/ambiguity are excluded from the denominator; no comparable bases is
    missing data, never zero identity. Reverse records already share orientation.
    """
    reference = next((m for m in block['members'] if m['genome_id'] == reference_id), None)
    if reference is None:
        return {'reference_id': reference_id, 'present': False, 'members': []}
    width = max(1, (block['columns'] + bins - 1) // bins)
    profiles = []
    for member in block['members']:
        if member['genome_id'] == reference_id:
            continue
        coordinate = member['start'] if member['strand'] == '+' else member['end']
        step = 1 if member['strand'] == '+' else -1
        windows = []
        totals = {'matches': 0, 'substitutions': 0, 'gap_columns': 0, 'ambiguous_columns': 0}
        for offset in range(0, block['columns'], width):
            bases = member['sequence'][offset:offset + width]
            refs = reference['sequence'][offset:offset + width]
            count = len(bases) - bases.count('-')
            comparable = matches = 0
            gaps = 0
            for start in range(0, len(bases), SCAN_CHUNK):
                a = np.frombuffer(bases[start:start + SCAN_CHUNK].encode('ascii'), dtype=np.uint8)
                b = np.frombuffer(refs[start:start + SCAN_CHUNK].encode('ascii'), dtype=np.uint8)
                valid = CANONICAL[a] & CANONICAL[b]
                comparable += int(np.count_nonzero(valid))
                matches += int(np.count_nonzero((a == b) & valid))
                gaps += int(np.count_nonzero((a == 45) | (b == 45)))
            totals['matches'] += matches
            totals['substitutions'] += comparable - matches
            totals['gap_columns'] += gaps
            totals['ambiguous_columns'] += len(bases) - comparable - gaps
            if count:
                last = coordinate + step * (count - 1)
                windows.append({'start': min(coordinate, last), 'end': max(coordinate, last),
                                'identity': matches / comparable if comparable else None,
                                'compared': comparable, 'columns': len(bases)})
            coordinate += step * count
        profiles.append({'genome_id': member['genome_id'], 'windows': windows, **totals})
    return {'reference_id': reference_id, 'present': True, 'members': profiles}


def coordinate_column(member, position):
    """Map a native 1-based base position to its zero-based alignment column."""
    if not member['start'] <= position <= member['end']:
        raise ValueError('Position is outside this block member.')
    target = (position - member['start'] if member['strand'] == '+'
              else member['end'] - position)
    sequence = member['sequence']
    # Lower-bound search over ungapped prefix lengths. str.count scans in C;
    # no Python iteration over millions of preceding alignment columns.
    low, high = 0, len(sequence)
    while low < high:
        middle = (low + high) // 2
        consumed = middle + 1 - sequence.count('-', 0, middle + 1)
        if consumed <= target:
            low = middle + 1
        else:
            high = middle
    if low == len(sequence):
        raise ValueError('Position has no aligned base.')
    return low


def next_difference(block, after=0):
    """First unequal column across all members, including gaps and ambiguity."""
    sequences = [m['sequence'] for m in block['members']]
    if len(sequences) < 2:
        return None
    for start in range(after, block['columns'], SCAN_CHUNK):
        stop = min(start + SCAN_CHUNK, block['columns'])
        reference = np.frombuffer(sequences[0][start:stop].encode('ascii'), dtype=np.uint8)
        different = np.zeros(len(reference), dtype=np.bool_)
        for sequence in sequences[1:]:
            bases = np.frombuffer(sequence[start:stop].encode('ascii'), dtype=np.uint8)
            different |= bases != reference
        if different.any():
            return start + int(different.argmax())
    return None
