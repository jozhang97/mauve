// Byte sequences stay in the worker. Only metadata and requested pages reach the UI.
export const STRIDE = 1024;
const encoder = new TextEncoder(), decoder = new TextDecoder();
export const basename = s => s.replaceAll('\\', '/').split('/').pop();
export function indexMember(member) {
  const sequence = typeof member.sequence === 'string' ? encoder.encode(member.sequence) : member.sequence;
  const prefix = new Uint32Array(Math.floor(sequence.length / STRIDE) + 1);
  let count = 0;
  for (let start = 0; start < sequence.length; start += STRIDE) {
    prefix[start / STRIDE] = count;
    const end = Math.min(start + STRIDE, sequence.length);
    for (let i = start; i < end; i++) if (sequence[i] !== 45) count++;
  }
  if (sequence.length % STRIDE === 0) prefix[sequence.length / STRIDE] = count;
  return {...member, sequence, prefix};
}
export function consumed(m, offset) {
  const page = Math.floor(offset / STRIDE);
  let n = m.prefix[page];
  for (let i = page * STRIDE; i < offset; i++) if (m.sequence[i] !== 45) n++;
  return n;
}
export function metadata(m) {
  return {genome_id: m.genome_id, start: m.start, end: m.end, strand: m.strand};
}
export function columnSlice(m, offset, limit) {
  let position = (m.strand === '+' ? m.start : m.end) + (m.strand === '+' ? 1 : -1) * consumed(m, offset);
  const bytes = m.sequence.subarray(offset, offset + limit), positions = [];
  for (const b of bytes) {
    positions.push(b === 45 ? null : position);
    if (b !== 45) position += m.strand === '+' ? 1 : -1;
  }
  return {...metadata(m), bases: decoder.decode(bytes), positions};
}
export function coordinateColumn(m, position) {
  if (!Number.isSafeInteger(position) || position < m.start || position > m.end) throw Error('Position is outside this block member.');
  const target = m.strand === '+' ? position - m.start : m.end - position;
  let lo = 0, hi = m.prefix.length;
  while (lo < hi) { const mid = (lo + hi) >>> 1; if (m.prefix[mid] <= target) lo = mid + 1; else hi = mid; }
  let count = m.prefix[lo - 1];
  for (let i = (lo - 1) * STRIDE; i < m.sequence.length; i++) {
    if (m.sequence[i] !== 45 && count++ === target) return i;
  }
  throw Error('Position has no aligned base.');
}
export function nextDifference(block, after = 0) {
  const ref = block.members[0].sequence;
  // Chunk/member/column order avoids per-base object iteration for many genomes.
  for (let start = after; start < block.columns; start += 65536) {
    let first = Math.min(start + 65536, block.columns);
    for (let m = 1; m < block.members.length; m++) {
      const seq = block.members[m].sequence;
      for (let i = start; i < first; i++) if (seq[i] !== ref[i]) { first = i; break; }
    }
    if (first < Math.min(start + 65536, block.columns)) return first;
  }
  return null;
}
export const canonical = b => b === 65 || b === 67 || b === 71 || b === 84;
const canonicalBytes = new Uint8Array(256);
for (const base of [65, 67, 71, 84]) canonicalBytes[base] = 1;
export function pairCounts(a, b, width) {
  const result = new Uint32Array(Math.ceil(a.length / width) * 4);
  for (let bin = 0, start = 0; start < a.length; bin++, start += width) {
    let matches = 0, compared = 0, gaps = 0;
    const end = Math.min(start + width, a.length);
    for (let i = start; i < end; i++) {
      const x = a[i], y = b[i];
      if (x === 45 || y === 45) gaps++;
      else if (canonicalBytes[x] && canonicalBytes[y]) { compared++; if (x === y) matches++; }
    }
    result.set([matches, compared, gaps, end - start - compared - gaps], bin * 4);
  }
  return result;
}
export function profileMember(m, columns, width, counts) {
  const windows = [], totals = {matches: 0, substitutions: 0, gap_columns: 0, ambiguous_columns: 0};
  let before = 0;
  for (let i = 0, offset = 0; offset < columns; i++, offset += width) {
    const end = Math.min(offset + width, columns), after = consumed(m, end), count = after - before;
    const matches = counts[i * 4], compared = counts[i * 4 + 1], gaps = counts[i * 4 + 2], ambiguous = counts[i * 4 + 3];
    totals.matches += matches; totals.substitutions += compared - matches;
    totals.gap_columns += gaps; totals.ambiguous_columns += ambiguous;
    if (count) {
      const first = m.strand === '+' ? m.start + before : m.end - before;
      const last = first + (m.strand === '+' ? 1 : -1) * (count - 1);
      windows.push({start: Math.min(first, last), end: Math.max(first, last), identity: compared ? matches / compared : null, compared, columns: end - offset});
    }
    before = after;
  }
  return {genome_id: m.genome_id, windows, ...totals};
}
export async function* lineBatches(blob, trim = true) {
  const normalize = trim ? line => line.trim() : line => line.endsWith("\r") ? line.slice(0, -1) : line;
  const reader = blob.stream().pipeThrough(new TextDecoderStream('utf-8', {fatal: true})).getReader();
  let pending = [];
  try {
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      let batch = [];
      let start = 0, end;
      // Search only this chunk. Unwrapped chromosome lines may span hundreds
      // of chunks; repeatedly concatenating and rescanning them is quadratic.
      while ((end = value.indexOf('\n', start)) !== -1) {
        const part = value.slice(start, end);
        if (pending.length) {
          pending.push(part);
          const line = pending.join(''); pending = [];
          batch.push(normalize(line));
        } else batch.push(normalize(part));
        start = end + 1;
        // Bound temporary arrays even when Node supplies a whole Blob at once.
        if (batch.length === 1024) { yield batch; batch = []; }
      }
      if (start < value.length) pending.push(value.slice(start));
      if (batch.length) yield batch;
    }
    if (pending.length) yield [normalize(pending.join(''))];
  } finally { reader.releaseLock(); }
}
export async function* lines(blob) {
  for await (const batch of lineBatches(blob)) for (const line of batch) yield line;
}
export async function parseXMFA(blob, saveBlock) {
  const genomes = new Map(); let current = null, members = [], blockCount = 0, lineNumber = 0;
  const finish = () => {
    if (!current) return;
    const sequence = current.parts.join('').toUpperCase(); delete current.parts;
    if (current.start === 0 && current.end === 0) {
      if (/[^-]/.test(sequence)) throw Error('Absent (0-0) records must contain only gaps.');
      current = null; return;
    }
    if (current.start < 1 || current.end < current.start) throw Error('Coordinates must be positive and start must not exceed end.');
    const member = indexMember({...current, sequence});
    // The rank index already counted every full stride; only inspect its tail.
    const count = consumed(member, member.sequence.length);
    if (count !== current.end - current.start + 1) throw Error('Coordinate span does not match ungapped bases.');
    if (members.some(m => m.genome_id === current.genome_id)) throw Error('A block contains the same sequence more than once.');
    genomes.get(current.genome_id).extent = Math.max(genomes.get(current.genome_id).extent, current.end);
    members.push(member); current = null;
  };
  const flush = async () => {
    finish(); if (!members.length) return;
    const columns = members[0].sequence.length;
    if (members.some(m => m.sequence.length !== columns)) throw Error('Aligned sequences within a block must have equal column counts.');
    await saveBlock({id: ++blockCount, columns, members}); members = [];
  };
  for await (const batch of lineBatches(blob)) for (const line of batch) {
    lineNumber++;
    if (!line) continue;
    const meta = line.match(/^#Sequence(\d+)File\s+(.+)$/);
    if (meta) {
      const id = Number(meta[1]); if (!genomes.has(id)) genomes.set(id, {id, name: basename(meta[2]), extent: 0});
    } else if (line[0] === '#') continue;
    else if (line[0] === '>') {
      finish(); const match = line.match(/^>\s*(\d+):(\d+)-(\d+)\s+([+-])(?:\s+(.*))?$/);
      if (!match) throw Error(`Invalid XMFA sequence header at line ${lineNumber}.`);
      const [id, start, end] = match.slice(1, 4).map(Number);
      if (![id, start, end].every(Number.isSafeInteger) || id < 1) throw Error('Invalid sequence ID or coordinates.');
      if (!genomes.has(id)) genomes.set(id, {id, name: basename(match[5] || `Sequence ${id}`), extent: 0});
      current = {genome_id: id, start, end, strand: match[4], parts: []};
    } else if (line[0] === '=') await flush();
    else if (current && /^[ACGTRYSWKMBDHVNacgtryswkmbdhvn-]+$/.test(line)) current.parts.push(line);
    else throw Error(`Unexpected content at line ${lineNumber}; expected XMFA aligned DNA.`);
  }
  await flush();
  if (!blockCount) throw Error('No aligned sequence blocks found. Upload an XMFA or Mauve .alignment file.');
  return {genomes: [...genomes.values()].filter(g => g.extent).sort((a, b) => a.id - b.id), block_count: blockCount};
}
