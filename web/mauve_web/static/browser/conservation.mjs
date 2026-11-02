// Port of SimilarityIndex and ZoomHistogram. Coordinates/index rounding deliberately
// follow the Java viewer; display normalization belongs here, not in the renderer.
export const charMap = new Uint8Array(256);
for (const [letters, value] of [['A', 0], ['C', 1], ['G', 2], ['T', 3], ['-NX', 4], ['RMWVDH', 0], ['K', 2], ['SYB', 1]]) {
  if (value >= 0) for (const c of letters) charMap[c.charCodeAt(0)] = charMap[c.toLowerCase().charCodeAt(0)] = value;
}
const reverseMap = charMap.slice();
for (let i = 0; i < 'ACGTRYKMSWBVDHNX-'.length; i++) {
  const a = 'ACGTRYKMSWBVDHNX-'[i], b = 'TGCAYRMKSWVBHDNX-'[i];
  reverseMap[a.charCodeAt(0)] = reverseMap[a.toLowerCase().charCodeAt(0)] = charMap[b.charCodeAt(0)];
}
export function entropy(counts) {
  const n = counts.reduce((a, b) => a + b, 0);
  if (!n) return 0;
  let h = 0;
  for (let i = 0; i < 4; i++) if (counts[i]) h -= counts[i] / n * (Math.log(counts[i] / n) / Math.log(2));
  return h + counts[4] / n * (Math.log(n) / Math.log(2));
}
export const quantize = h => ((1 - h) - 0.5) * 255 < -127 ? -128 : Math.trunc(((1 - h) - 0.5) * 255);
export const normalize = s => Math.max(0, Math.min(1, (s + 127) / 256));
export class Histogram {
  constructor(base, length) {
    this.length = length;
    this.levels = [{mean: base, min: base, max: base, resolution: 5}];
    while (base.length > 500) {
      const n = Math.floor(base.length / 8), mean = new Int8Array(n), min = new Int8Array(n), max = new Int8Array(n);
      for (let i = 0; i < n; i++) {
        let sum = 0, lo = 127, hi = -128;
        for (let j = i * 8; j < i * 8 + 8; j++) { sum += base[j]; lo = Math.min(lo, base[j]); hi = Math.max(hi, base[j]); }
        mean[i] = Math.trunc(sum / 8); min[i] = lo; max[i] = hi;
      }
      // Java stores extrema of child MEANS, not transitive extrema.
      this.levels.push({mean, min, max, resolution: this.levels.at(-1).resolution * 8}); base = mean;
    }
  }
  value(left, right, type = 0) {
    if (right - left + 1 < 10) { left = Math.max(0, left - Math.trunc((10 - (right - left)) / 2)); right = left + 10; }
    const size = right - left;
    let level = this.levels.length - 1;
    while (level > 0 && this.levels[level].resolution * 2 >= size) level--;
    const data = this.levels[level], r = data.resolution;
    const first = Math.max(0, Math.min(data.mean.length - 1, Math.ceil(left / r)));
    const last = Math.max(first, Math.min(data.mean.length - 1, Math.floor(right / r)));
    const array = type < 0 ? data.min : type > 0 ? data.max : data.mean;
    let s = type < 0 ? 127 : type > 0 ? -128 : 0;
    for (let i = first; i <= last; i++) s = type < 0 ? Math.min(s, array[i]) : type > 0 ? Math.max(s, array[i]) : s + array[i];
    if (!type) s = Math.trunc(s / (last - first + 1));
    const ls = first * r - left, rs = right - (last + 1) * r;
    const a = ls > 5 && level > 0 ? (first * r === right ? 0 : this.value(left, first * r, type)) : s;
    const b = rs > 5 && level > 0 ? ((last + 1) * r === left ? 0 : this.value((last + 1) * r, right, type)) : s;
    return type < 0 ? Math.min(a, s, b) : type > 0 ? Math.max(a, s, b) : Math.trunc((ls * a + rs * b + s * (size - ls - rs)) / size);
  }
}

// .bbcols uses zero-based block/genome indexes and one-based alignment columns.
// This is the BackboneFile format consumed by the original Java viewer.
export function parseBackbone(text, blocks, genomes) {
  const result = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim() || line.startsWith('#')) continue;
    const fields = line.trim().split(/\s+/).map(Number);
    if (fields.some(x => !Number.isSafeInteger(x))) throw Error('Expected Mauve .bbcols backbone data (block, column, length, genome indexes).');
    const [index, left, length, ...seqs] = fields, block = blocks[index];
    if (!block || left < 1 || length < 1 || left + length - 1 > block.columns || !seqs.length || new Set(seqs).size !== seqs.length || seqs.some(i => i < 0 || i >= genomes.length || !block.members.some(m => m.genome_id === genomes[i].id))) throw Error('Backbone segment does not match this alignment.');
    result.push({block_id: block.id, left: left - 1, right: left + length - 1, genomes: seqs.map(i => genomes[i].id)});
  }
  result.sort((a, b) => a.block_id - b.block_id || a.left - b.left);
  const ends = new Map();
  for (const segment of result) for (const gid of segment.genomes) {
    const key = `${segment.block_id}/${gid}`;
    if (segment.left < (ends.get(key) ?? -1)) throw Error('Backbone segments overlap within one genome.');
    ends.set(key, segment.right);
  }
  return result;
}

export async function buildConservation(genomes, blocks, load, backbone = null, progress = () => {}) {
  const n = genomes.length, missing = (Math.log(n) / Math.log(2)), sums = new Map(), segments = new Map();
  // At most ~160 MiB scratch for the browser aligner's 100-million-base budget.
  const total = genomes.reduce((sum, g) => sum + Math.max(1, Math.floor(g.extent / 5)), 0);
  if (total > 32 * 1024 * 1024) throw Error('Conservation index exceeds the 256 MiB working-memory limit.');
  for (const g of genomes) { sums.set(g.id, new Float64Array(Math.max(1, Math.floor(g.extent / 5))).fill(missing * Math.min(5, g.extent))); segments.set(g.id, []); }
  const lengths = new Map(genomes.map(g => [g.id, g.extent]));
  for (const info of blocks) {
    progress(`Computing conservation: block ${info.id}/${blocks.length}…`);
    const block = await load(info), members = block.members;
    const positions = members.map(m => m.strand === '+' ? m.start : m.end);
    const steps = members.map(m => m.strand === '+' ? 1 : -1);
    const bb = backbone?.filter(b => b.block_id === block.id) || []; let bi = 0;
    const full = {genomes: genomes.map(g=>g.id), right: block.columns};
    let groups = [], memberGroups = members.map(() => null), nextBoundary = 0;
    for (let col = 0; col < block.columns; col++) {
      if (col >= nextBoundary) {
        groups = groups.filter(group => col < group.segment.right);
        if (backbone === null && !groups.length) groups.push({segment: full});
        while (bi < bb.length && bb[bi].left <= col) groups.push({segment: bb[bi++]});
        nextBoundary = Math.min(block.columns, bi < bb.length ? bb[bi].left : block.columns, ...groups.map(g=>g.segment.right));
        for (const group of groups) {
          group.indices = members.map((m,i)=>group.segment.genomes.includes(m.genome_id)?i:-1).filter(i=>i>=0);
          group.counts = new Float64Array(5); group.reverseCounts = new Float64Array(5);
        }
        memberGroups = members.map(m=>groups.find(g=>g.segment.genomes.includes(m.genome_id)));
      }
      for (const group of groups) {
        const {counts, reverseCounts} = group;
        counts.fill(0); reverseCounts.fill(0);
        if (backbone === null) counts[4] = reverseCounts[4] = n - members.length;
        for (const mi of group.indices) {
          const c = members[mi].sequence[col]; counts[charMap[c]]++; reverseCounts[reverseMap[c]]++;
        }
        group.h = entropy(counts); group.reverseH = entropy(reverseCounts);
      }
      for (let mi = 0; mi < members.length; mi++) {
        const m = members[mi]; if (m.sequence[col] === 45) continue;
        const pos = positions[mi], len = lengths.get(m.genome_id), a = sums.get(m.genome_id);
        const group = memberGroups[mi], segment = group?.segment, inside = backbone !== null && Boolean(group);
        const delta = (!group ? missing : m.strand === '-' ? group.reverseH : group.h) - missing;
        const bin = Math.floor((pos - 1) / 5), shifted = len >= 10 && len % 5 === 0;
        if (bin < a.length && !(shifted && bin === a.length - 1)) a[bin] += delta;
        if (shifted && pos >= len - 5 && pos < len) a[a.length - 1] += delta;
        if (inside) {
          const list = segments.get(m.genome_id), last = list.at(-1);
          if (last && last.segment === segment && Math.abs(pos - last.last) === 1) { last.start = Math.min(last.start, pos); last.end = Math.max(last.end, pos); last.last = pos; }
          else list.push({start: pos, end: pos, last: pos, segment});
        }
        positions[mi] += steps[mi];
      }
      // Yield so worker navigation messages can be received during long scans.
      if (col && col % 65536 === 0) await new Promise(resolve => setTimeout(resolve, 0));
    }
  }
  const indexes = new Map();
  for (const g of genomes) {
    const a = sums.get(g.id), base = Int8Array.from(a, sum => quantize(sum / Math.min(5, g.extent)));
    indexes.set(g.id, {histogram: new Histogram(base, g.extent), segments: segments.get(g.id).map(({start, end}) => ({start, end})).sort((a,b) => a.start-b.start), backbone: backbone !== null});
    sums.delete(g.id);
  }
  progress(''); return indexes;
}
export function sampleConservation(indexes, ranges) {
  if (!Array.isArray(ranges) || ranges.length > 10000) throw Error('Invalid conservation ranges.');
  let budget = 0;
  return ranges.map(range => {
    const {genome_id, start, end, bins} = range, index = indexes.get(genome_id);
    if (!index || ![start, end, bins].every(Number.isSafeInteger) || start < 1 || end < start || end > index.histogram.length || bins < 1 || bins > 8192 || (budget += bins) > 200000) throw Error('Invalid conservation range.');
    const samples = []; let si = 0;
    for (let i = 0; i < bins; i++) {
      const left = Math.floor(start + (end + 1 - start) * i / bins), right = Math.min(index.histogram.length, Math.floor(start + (end + 1 - start) * (i + 1) / bins));
      while (si < index.segments.length && index.segments[si].end < left) si++;
      const inside = !index.backbone || (si < index.segments.length && index.segments[si].start <= right);
      samples.push([normalize(index.histogram.value(left,right)), normalize(index.histogram.value(left,right,-1)), normalize(index.histogram.value(left,right,1)), inside ? 1 : 0]);
    }
    return {...range, samples};
  });
}
