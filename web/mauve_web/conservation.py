"""Mauve SimilarityIndex/ZoomHistogram conservation, in native genome coordinates."""
import math
import numpy as np

CHAR_MAP = np.zeros(256, dtype=np.uint8)
for letters, value in [('A', 0), ('C', 1), ('G', 2), ('T', 3), ('-NX', 4), ('RMWVDH', 0), ('K', 2), ('SYB', 1)]:
    for c in letters + letters.lower():
        CHAR_MAP[ord(c)] = value

REVERSE_MAP = CHAR_MAP.copy()
for a, b in zip('ACGTRYKMSWBVDHNX-', 'TGCAYRMKSWVBHDNX-'):
    REVERSE_MAP[ord(a)] = REVERSE_MAP[ord(a.lower())] = CHAR_MAP[ord(b)]


class Histogram:
    def __init__(self, base, length):
        self.length = length
        self.levels = [(base, base, base, 5)]
        while len(base) > 500:
            groups = base[:len(base) // 8 * 8].reshape(-1, 8)
            mean = np.trunc(groups.mean(axis=1)).astype(np.int8)
            self.levels.append((mean, groups.min(axis=1), groups.max(axis=1), self.levels[-1][3] * 8))
            base = mean

    def value(self, left, right, kind=0):
        if right - left + 1 < 10:
            left = max(0, left - (10 - (right - left)) // 2)
            right = left + 10
        size = right - left
        level = len(self.levels) - 1
        while level > 0 and self.levels[level][3] * 2 >= size:
            level -= 1
        mean, low, high, res = self.levels[level]
        first = max(0, min(len(mean) - 1, math.ceil(left / res)))
        last = max(first, min(len(mean) - 1, right // res))
        array = low if kind < 0 else high if kind > 0 else mean
        part = array[first:last + 1]
        s = int(part.min()) if kind < 0 else int(part.max()) if kind > 0 else math.trunc(float(part.mean()))
        ls, rs = first * res - left, right - (last + 1) * res
        a = (0 if first * res == right else self.value(left, first * res, kind)) if ls > 5 and level > 0 else s
        b = (0 if (last + 1) * res == left else self.value((last + 1) * res, right, kind)) if rs > 5 and level > 0 else s
        return min(a, s, b) if kind < 0 else max(a, s, b) if kind > 0 else math.trunc((ls * a + rs * b + s * (size - ls - rs)) / size)


def parse_backbone(text, blocks, genomes):
    result = []
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        try:
            index, left, length, *seqs = map(int, line.split())
            block = blocks[index] if index >= 0 else None
            if (not block or left < 1 or length < 1 or left + length - 1 > block['columns'] or not seqs or len(set(seqs)) != len(seqs)
                    or any(i < 0 or i >= len(genomes) or not any(m['genome_id'] == genomes[i]['id'] for m in block['members']) for i in seqs)):
                raise ValueError()
            result.append(dict(block_id=block['id'], left=left - 1, right=left + length - 1, genomes=[genomes[i]['id'] for i in seqs]))
        except (ValueError, IndexError):
            raise ValueError('Expected matching Mauve .bbcols backbone data (block, column, length, genome indexes).') from None
    result.sort(key=lambda b: (b['block_id'], b['left']))
    ends = {}
    for segment in result:
        for gid in segment['genomes']:
            key = (segment['block_id'], gid)
            if segment['left'] < ends.get(key, -1):
                raise ValueError('Backbone segments overlap within one genome.')
            ends[key] = segment['right']
    return result


def build_conservation(genomes, blocks, load, backbone=None):
    n = len(genomes)
    missing = math.log2(n)
    if sum(max(1, g['extent'] // 5) for g in genomes) > 32 * 1024 * 1024:
        raise ValueError('Conservation index exceeds the 256 MiB working-memory limit.')
    sums = {g['id']: np.full(max(1, g['extent'] // 5), missing * min(5, g['extent'])) for g in genomes}
    lengths = {g['id']: g['extent'] for g in genomes}
    segments = {g['id']: [] for g in genomes}
    for info in blocks:
        block = load(info)
        members = block['members']
        arrays = [np.frombuffer(m['sequence'].encode('ascii'), dtype=np.uint8) for m in members]
        offsets = [0] * len(members)
        bb = [b for b in backbone or [] if b['block_id'] == block['id']]
        # Split at backbone boundaries so every chunk has one participating set.
        boundaries = sorted({0, block['columns'], *(b[k] for b in bb for k in ('left', 'right'))})
        for left, right in zip(boundaries, boundaries[1:]):
            groups = [b['genomes'] for b in bb if b['left'] <= left < b['right']] if backbone is not None else [[g['id'] for g in genomes]]
            member_groups = {gid: i for i, group in enumerate(groups) for gid in group}
            for start in range(left, right, 65536):
                end = min(right, start + 65536)
                entropies = []
                for group in groups:
                    counts = np.zeros((5, end - start))
                    reverse_counts = np.zeros_like(counts)
                    if backbone is None:
                        counts[4] = reverse_counts[4] = n - len(members)
                    for m, seq in zip(members, arrays):
                        if m['genome_id'] in group:
                            chars, reverse_chars = CHAR_MAP[seq[start:end]], REVERSE_MAP[seq[start:end]]
                            for c in range(5):
                                counts[c] += chars == c
                                reverse_counts[c] += reverse_chars == c
                    safe = np.maximum(1, counts.sum(axis=0))
                    probs = counts[:4] / safe
                    h = -(probs * np.log2(np.maximum(probs, np.finfo(float).tiny))).sum(axis=0) + counts[4] / safe * np.log2(safe)
                    reverse_probs = reverse_counts[:4] / safe
                    reverse_h = -(reverse_probs * np.log2(np.maximum(reverse_probs, np.finfo(float).tiny))).sum(axis=0) + reverse_counts[4] / safe * np.log2(safe)
                    entropies.append((h, reverse_h))
                for mi, (m, seq) in enumerate(zip(members, arrays)):
                    gid = m['genome_id']
                    mask = seq[start:end] != 45
                    count = int(mask.sum())
                    if not count:
                        continue
                    positions = np.arange(offsets[mi], offsets[mi] + count, dtype=np.int64)
                    positions = m['start'] + positions if m['strand'] == '+' else m['end'] - positions
                    offsets[mi] += count
                    group = member_groups.get(gid)
                    delta = entropies[group][int(m['strand'] == '-')][mask] - missing if group is not None else np.zeros(count)
                    a, length = sums[gid], lengths[gid]
                    bins = (positions - 1) // 5
                    shifted = length >= 10 and length % 5 == 0
                    valid = (bins < len(a) - (1 if shifted else 0))
                    np.add.at(a, bins[valid], delta[valid])
                    if shifted:
                        a[-1] += delta[(positions >= length - 5) & (positions < length)].sum()
                    if backbone is not None and group is not None:
                        segments[gid].append(dict(start=int(positions.min()), end=int(positions.max())))
    result = {}
    for g in genomes:
        values = ((1 - sums.pop(g['id']) / min(5, g['extent'])) - 0.5) * 255
        base = np.where(values < -127, -128, np.trunc(values)).astype(np.int8)
        result[g['id']] = (Histogram(base, g['extent']), sorted(segments[g['id']], key=lambda s: s['start']), backbone is not None)
    return result


def sample_conservation(indexes, ranges):
    if not isinstance(ranges, list) or len(ranges) > 10000:
        raise ValueError('Invalid conservation ranges.')
    budget = 0
    result = []
    for r in ranges:
        try:
            gid, start, end, bins = (r[k] for k in ('genome_id', 'start', 'end', 'bins'))
            hist, segments, backbone = indexes[gid]
            budget += bins
            if (any(type(x) is not int for x in (start, end, bins)) or start < 1 or end < start or end > hist.length or not 1 <= bins <= 8192 or budget > 200000):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ValueError('Invalid conservation range.') from None
        samples, si = [], 0
        for i in range(bins):
            left = math.floor(start + (end + 1 - start) * i / bins)
            right = min(hist.length, math.floor(start + (end + 1 - start) * (i + 1) / bins))
            while si < len(segments) and segments[si]['end'] < left:
                si += 1
            inside = not backbone or (si < len(segments) and segments[si]['start'] <= right)
            samples.append([*(max(0, min(1, (hist.value(left, right, kind) + 127) / 256)) for kind in (0, -1, 1)), int(inside)])
        result.append({**r, 'samples': samples})
    return result
