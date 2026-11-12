// Reference assay evidence is attached only to identical, complete CDS sequences.
// Sequence identity does not establish essentiality in a different strain.
const complement = {65:84, 84:65, 67:71, 71:67};
export async function hashCodingSequences(parsed) {
  for (const f of parsed.features) {
    if (f.type !== 'CDS' || f.pseudo || !['+', '-'].includes(f.strand) || f.parts.some(p => p.fuzzy)) continue;
    const sequence = new Uint8Array(f.parts.reduce((n, p) => n + p.end - p.start + 1, 0));
    let at = 0;
    for (const p of f.parts) {
      const bases = parsed.sequence.subarray(p.start - 1, p.end);
      if (p.strand === '+') { sequence.set(bases, at); at += bases.length; }
      else for (let i = bases.length - 1; i >= 0; i--) sequence[at++] = complement[bases[i]] || bases[i];
    }
    if (sequence.some(b => ![65, 67, 71, 84].includes(b))) continue;
    f.sequence_sha256 = [...new Uint8Array(await crypto.subtle.digest('SHA-256', sequence))].map(b => b.toString(16).padStart(2, '0')).join('');
  }
}

export function annotateEssentiality(result, snapshot) {
  // Validate before mutating results, so a damaged snapshot cannot leave partial calls.
  if (snapshot?.schema_version !== 1 || !snapshot.source?.strain || !snapshot.source?.publication ||
      !snapshot.sequences || typeof snapshot.sequences !== 'object' || Array.isArray(snapshot.sequences))
    throw Error('Invalid essentiality snapshot');
  for (const [hash, records] of Object.entries(snapshot.sequences)) {
    if (!/^[a-f0-9]{64}$/.test(hash) || !Array.isArray(records) || !records.length || records.some(r =>
      !r || typeof r.gene !== 'string' || typeof r.locus_tag !== 'string' || !['essential', 'nonessential', 'unclear'].includes(r.status)))
      throw Error('Invalid essentiality evidence');
  }
  const codingGenes = result.families.flatMap(f => f.members).filter(m => m.type === 'CDS');
  if (codingGenes.length && !codingGenes.some(m => m.sequence_sha256))
    throw Error('CDS sequence checksums are missing. Reopen the bundled demo or reimport annotations, then recompute gene comparisons.');
  result.essentiality_source = snapshot.source;
  for (const family of result.families) {
    const evidence = new Map();
    for (const member of family.members) {
      const matches = snapshot.sequences[member.sequence_sha256] || [];
      member.essentiality = {status: matches.length ? [...new Set(matches.map(m => m.status))].sort().join(' / ') : 'unknown',
        basis: matches.length ? 'identical CDS sequence; strain essentiality not established' : member.sequence_sha256 ? 'no sequence match' : 'CDS checksum unavailable; reimport annotations', evidence: matches};
      for (const match of matches) evidence.set(`${match.locus_tag}:${match.status}`, match);
    }
    family.essentiality = {status: evidence.size ? [...new Set([...evidence.values()].map(e => e.status))].sort().join(' / ') : 'unknown',
      evidence: [...evidence.values()]};
  }
}

// Choose by exact CDS evidence, never by a gene name or a species-name guess.
export function annotateEssentialityReferences(result, snapshots) {
  if (!snapshots.length) throw Error('No essentiality reference snapshots available.');
  const members = result.families.flatMap(f => f.members);
  const counts = snapshots.map(snapshot => members.reduce((n, m) => n + Boolean(snapshot.sequences?.[m.sequence_sha256]), 0));
  const index = counts.indexOf(Math.max(...counts));
  annotateEssentiality(result, snapshots[index]);
  result.essentiality_matched_copies = counts[index];
  result.essentiality_reference_note = counts[index]
    ? `${snapshots[index].source.method}. Calls require an identical complete CDS; sequence variants and untested genes remain unknown.`
    : 'No identical CDS matches to the bundled reference assays. Unknown means no matching evidence, not nonessentiality.';
}
