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
      record = {name: fields[1], declared: Number(fields[2]), topology: fields.includes('circular') ? 'circular' : fields.includes('linear') ? 'linear' : 'unknown', parts: [], features: []}; origin = features = false;
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
export function annotationData(records, concatenate, rotation = 0) {
  if (records.length > 1 && !concatenate) throw Error('This file contains multiple records. Enable concatenation only if the alignment uses these records in file order.');
  const features = [], contigs = []; let offset = 0;
  for (const r of records) {
    contigs.push({name: r.name, start: offset + 1, end: offset + r.sequence.length, topology: r.topology});
    for (const f of r.features) {
      if (f.type === 'source') continue;
      let parts = locationParts(f.location, r.sequence.length, offset);
      if (rotation) {
        if (records.length !== 1) throw Error('Rotation requires a single chromosome.');
        parts = parts.flatMap(p => {
          const n = r.sequence.length;
          const start = (p.start - 1 - rotation + n) % n + 1;
          const end = (p.end - 1 - rotation + n) % n + 1;
          if (start <= end) return [{...p, start, end}];
          const split = [{...p, start, end:n}, {...p, start:1, end}];
          return p.strand === '-' ? split.reverse() : split;
        });
      }
      const value = k => (f.qualifiers[k] || []).map(s => s.replace(/^"|"$/g, '').replaceAll('""', '"')).join('; ');
      features.push({name: value('gene') || value('locus_tag') || value('label') || f.type, type: f.type,
        locus_tag: value('locus_tag'), product: value('product'), note: value('note'), record: r.name,
        pseudo: 'pseudo' in f.qualifiers || 'pseudogene' in f.qualifiers,
        experiment: value('experiment'), inference: value('inference'),
        start: Math.min(...parts.map(p => p.start)), end: Math.max(...parts.map(p => p.end)),
        strand: parts.every(p => p.strand === parts[0].strand) ? parts[0].strand : '.', location: f.location, parts});
    }
    offset += r.sequence.length;
  }
  if (!features.length) throw Error('No non-source annotations were found in this GenBank file.');
  const sequence = new Uint8Array(offset); let at = 0;
  for (const r of records) { sequence.set(r.sequence, at); at += r.sequence.length; }
  if (rotation) {
    const rotated = new Uint8Array(sequence.length);
    rotated.set(sequence.subarray(rotation));
    rotated.set(sequence.subarray(0, rotation), sequence.length - rotation);
    return {features, records: contigs, length: offset, sequence: rotated};
  }
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
export async function normalizeInput(blob, normalizeOri = false, doric = null) {
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
  let ori = {requested: normalizeOri, status: normalizeOri ? 'unresolved' : 'disabled', source: null, offset: 0};
  if (normalizeOri && head.startsWith('LOCUS')) {
    if (records.length !== 1) ori.reason = 'multiple records';
    else if (records[0].topology !== 'circular') ori.reason = 'record is not circular';
    else {
      const annotated = records[0].features.filter(f => f.type === 'rep_origin');
      let candidate = null;
      if (annotated.length === 1) {
        const parts = locationParts(annotated[0].location, records[0].sequence.length);
        if (parts.some(p => p.fuzzy)) ori.reason = 'origin has uncertain boundaries';
        else candidate = {start: (parts[0].strand === '-' ? parts.at(-1) : parts[0]).start, source: 'annotated rep_origin'};
      } else if (annotated.length > 1) ori.reason = 'multiple rep_origin features';
      else {
        const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', records[0].sequence))].map(b => b.toString(16).padStart(2, '0')).join('');
        const matches = (doric?.records?.[records[0].name] || [])
          .filter(match => match.length === records[0].sequence.length &&
            (match.sha256 === digest || (match.sequence && Number.isInteger(match.start) && Number.isInteger(match.end) && match.start >= 1 && match.end <= records[0].sequence.length && match.start <= match.end &&
              new TextDecoder().decode(records[0].sequence.slice(match.start - 1, match.end)) === match.sequence.toUpperCase())));
        if (matches.length === 1) candidate = {start: matches[0].start, source: 'DoriC', doric_id: matches[0].id,
          release: doric.release, end: matches[0].end};
        else ori.reason = matches.length ? 'multiple DoriC candidates' : 'no origin found';
      }
      if (candidate) {
        const offset = candidate.start - 1, sequence = records[0].sequence;
        if (offset < 0 || offset >= sequence.length) throw Error('Origin coordinate lies outside its GenBank record.');
        if (offset) {
          const rotated = new Uint8Array(sequence.length);
          rotated.set(sequence.subarray(offset)); rotated.set(sequence.subarray(0, offset), sequence.length - offset);
          records[0].sequence = rotated;
        }
        ori = {requested: true, status: offset ? 'rotated' : 'already at oriC', offset, ...candidate};
      }
    }
  } else if (normalizeOri) ori.reason = 'FASTA has no origin annotation or accession';
  let bases = 0; const info = [], chunks = [encoder.encode('>genome\n')];
  for (const r of records) {
    if (!r.sequence.length || !/^[ACGTRYSWKMBDHVN]+$/.test(new TextDecoder().decode(r.sequence))) throw Error('Inputs must contain non-empty, ungapped DNA sequences (IUPAC bases).');
    info.push({name: r.name, start: bases + 1, end: bases + r.sequence.length}); bases += r.sequence.length;
    for (let i = 0; i < r.sequence.length; i += 65536) chunks.push(r.sequence.subarray(i, i + 65536), '\n');
  }
  if (bases < 50) throw Error('Each genome must contain at least 50 bases.');
  return {normalized: new Blob(chunks), records: info, bases, format: head.startsWith('>') ? 'fasta' : 'genbank', ori_normalization: ori};
}
