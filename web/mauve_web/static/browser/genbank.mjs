import {canonical, lineBatches} from './core.mjs';
const encoder = new TextEncoder();
const complement = Uint8Array.from({length: 256}, (_, i) => i);
complement[65] = 84; complement[84] = 65; complement[67] = 71; complement[71] = 67;
export async function parseRecords(blob) {
  const records = []; let record = null, feature = null, qualifier = null, origin = false, features = false;
  for await (const batch of lineBatches(blob, false)) for (const line of batch) {
    if (line.startsWith('LOCUS')) {
      if (record) throw Error('GenBank record missing // terminator.');
      const fields = line.trim().split(/\s+/);
      record = {name: fields[1], declared: Number(fields[2]), parts: [], features: []}; origin = features = false;
    } else if (line.startsWith('>')) {
      throw Error('Expected GenBank data.');
    } else if (record && /^(VERSION|ACCESSION)\s/.test(line)) {
      if (line.startsWith('VERSION') || !record.accession) record.name = line.trim().split(/\s+/)[1];
      record.accession = true;
    } else if (line.startsWith('FEATURES')) { features = true; feature = null; }
    else if (line.startsWith('ORIGIN')) { origin = true; features = false; }
    else if (line.startsWith('//')) {
      if (!record) throw Error('Unexpected GenBank terminator.');
      const sequence = record.parts.join('').toUpperCase();
      if (!sequence || !/^[ACGTRYSWKMBDHVN]+$/.test(sequence)) throw Error('GenBank records must include IUPAC DNA sequence.');
      if (sequence.length !== record.declared) throw Error('GenBank sequence length does not match LOCUS.');
      delete record.parts; record.sequence = encoder.encode(sequence); records.push(record); record = null;
    } else if (record && origin) record.parts.push(line.replace(/[\s\d]/g, ''));
    else if (record && features) {
      const key = line.slice(5, 21).trim(), value = line.slice(21).trim();
      if (key) { feature = {type: key, location: value, qualifiers: {}}; record.features.push(feature); qualifier = null; }
      else if (feature && value.startsWith('/')) {
        const match = value.match(/^\/([^=]+)(?:=(.*))?$/);
        qualifier = match[1];
        (feature.qualifiers[qualifier] ||= []).push(match[2] || '');
      } else if (feature && value) {
        if (qualifier) { const values = feature.qualifiers[qualifier]; values[values.length - 1] += ' ' + value; }
        else feature.location += value;
      }
    }
  }
  if (record) throw Error('GenBank record missing // terminator.');
  if (!records.length) throw Error('No GenBank records found.');
  return records;
}
export function locationParts(text, length, offset = 0, strand = '+') {
  text = text.replace(/\s/g, '');
  if (text.startsWith('complement(') && text.endsWith(')')) return locationParts(text.slice(11, -1), length, offset, strand === '+' ? '-' : '+').reverse();
  const compound = text.match(/^(join|order)\((.*)\)$/);
  if (compound) {
    const parts = []; let depth = 0, start = 0;
    for (let i = 0; i <= compound[2].length; i++) {
      const c = compound[2][i];
      if (c === '(') depth++; if (c === ')') depth--;
      if ((c === ',' && depth === 0) || i === compound[2].length) {
        parts.push(...locationParts(compound[2].slice(start, i), length, offset, strand)); start = i + 1;
      }
    }
    return parts;
  }
  const m = text.match(/^([<>]?)(\d+)(?:\.\.([<>]?)(\d+))?$/);
  if (!m) throw Error(`Unsupported GenBank location: ${text}. Remote, unknown, and between-base locations are not supported.`);
  const start = Number(m[2]), end = Number(m[4] || m[2]);
  if (start < 1 || start > end || end > length) throw Error('A feature location lies outside its record or has zero length.');
  return [{start: start + offset, end: end + offset, strand, fuzzy: Boolean(m[1] || m[3])}];
}
export function annotationData(records, concatenate) {
  if (records.length > 1 && !concatenate) throw Error('This file contains multiple records. Enable concatenation only if the alignment uses these records in file order.');
  const features = [], contigs = []; let offset = 0;
  for (const r of records) {
    contigs.push({name: r.name, start: offset + 1, end: offset + r.sequence.length});
    for (const f of r.features) {
      if (f.type === 'source') continue;
      const parts = locationParts(f.location, r.sequence.length, offset);
      const value = k => (f.qualifiers[k] || []).map(s => s.replace(/^"|"$/g, '').replaceAll('""', '"')).join('; ');
      features.push({name: value('gene') || value('locus_tag') || value('label') || f.type, type: f.type,
        locus_tag: value('locus_tag'), product: value('product'), note: value('note'), record: r.name,
        start: Math.min(...parts.map(p => p.start)), end: Math.max(...parts.map(p => p.end)),
        strand: parts.every(p => p.strand === parts[0].strand) ? parts[0].strand : '.', location: f.location, parts});
    }
    offset += r.sequence.length;
  }
  if (!features.length) throw Error('No non-source annotations were found in this GenBank file.');
  const sequence = new Uint8Array(offset); let at = 0;
  for (const r of records) { sequence.set(r.sequence, at); at += r.sequence.length; }
  return {features, records: contigs, length: offset, sequence};
}
export function verifyMember(m, sequence) {
  if (m.end > sequence.length) throw Error('GenBank sequence is shorter than the aligned coordinates for this genome.');
  const aligned = m.sequence, step = m.strand === '+' ? 1 : -1, reverse = m.strand === '-';
  let pos = step === 1 ? m.start - 1 : m.end - 1, count = 0;
  for (let column = 0; column < aligned.length; column++) {
    const actual = aligned[column];
    if (actual === 45) continue;
    let expected = sequence[pos];
    if (reverse) expected = complement[expected];
    if (canonical(actual) && canonical(expected)) {
      count++; if (actual !== expected) throw Error('GenBank sequence does not match the selected genome at aligned coordinates. Check the genome and record order.');
    }
    pos += step;
  }
  return count;
}
export async function normalizeInput(blob) {
  const head = (await blob.slice(0, 100).text()).trimStart(); let records;
  if (head.startsWith('LOCUS')) records = await parseRecords(blob);
  else if (head.startsWith('>')) {
    records = []; let record;
    for await (const batch of lineBatches(blob)) for (const line of batch) {
      if (!line) continue;
      if (line.startsWith('>')) { record = {name: line.slice(1).trim().split(/\s/)[0], parts: []}; records.push(record); }
      else { if (!record) throw Error('Expected a FASTA header.'); record.parts.push(line); }
    }
    for (const r of records) { r.sequence = encoder.encode(r.parts.join('').toUpperCase()); delete r.parts; }
  } else throw Error('Expected a FASTA or GenBank file with DNA sequences.');
  let bases = 0; const info = [], chunks = [encoder.encode('>genome\n')];
  for (const r of records) {
    if (!r.sequence.length || !/^[ACGTRYSWKMBDHVN]+$/.test(new TextDecoder().decode(r.sequence))) throw Error('Inputs must contain non-empty, ungapped DNA sequences (IUPAC bases).');
    info.push({name: r.name, start: bases + 1, end: bases + r.sequence.length}); bases += r.sequence.length;
    for (let i = 0; i < r.sequence.length; i += 65536) chunks.push(r.sequence.subarray(i, i + 65536), '\n');
  }
  if (bases < 50) throw Error('Each genome must contain at least 50 bases.');
  return {normalized: new Blob(chunks), records: info, bases, format: head.startsWith('>') ? 'fasta' : 'genbank'};
}
