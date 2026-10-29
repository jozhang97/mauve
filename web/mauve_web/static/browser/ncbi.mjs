import {Unzip, UnzipInflate} from '../vendor/fflate.mjs';
const BASE = 'https://api.ncbi.nlm.nih.gov/datasets/v2', MAX = 50 * 1024 * 1024;
let last = 0;
async function fetchNCBI(path, params = {}, limit = 8 * 1024 * 1024) {
  const wait = Math.max(0, last + 350 - Date.now()); last = Date.now() + wait;
  await new Promise(resolve => setTimeout(resolve, wait));
  const url = BASE + path + '?' + new URLSearchParams(params);
  let response;
  try { response = await fetch(url, {signal: AbortSignal.timeout(180000)}); }
  catch { throw Error('Could not reach NCBI from this browser. Check your network and try again, or import a downloaded genome file.'); }
  if (!response.ok) throw Error(response.status === 429 ? 'NCBI is rate limiting requests. Wait a moment and retry.' : `NCBI returned HTTP ${response.status}. Check the identifier or retry later.`);
  const chunks = []; let size = 0;
  const reader = response.body.getReader();
  try {
    while (true) {
      const {value, done} = await reader.read(); if (done) break;
      size += value.length; if (size > limit) throw Error('NCBI response exceeds the download size limit.'); chunks.push(value);
    }
  } finally { await reader.cancel(); }
  return new Blob(chunks);
}
const json = async (path, params) => JSON.parse(await (await fetchNCBI(path, params)).text());
export function summary(r) {
  const o = r.organism || {}, a = r.assembly_info || {}, s = r.assembly_stats || {};
  return {accession: r.accession, organism: o.organism_name || '', taxon_id: o.tax_id,
    strain: o.infraspecific_names?.strain || '', name: a.assembly_name || '', level: a.assembly_level || '',
    status: a.assembly_status || '', release_date: a.release_date || '', source: r.accession.startsWith('GCF') ? 'RefSeq' : 'GenBank',
    paired_accession: r.paired_accession || a.paired_assembly?.accession, reference_category: a.refseq_category || '',
    bases: Number(s.total_sequence_length || 0), contigs: s.number_of_contigs, contig_n50: s.contig_n50,
    url: `https://www.ncbi.nlm.nih.gov/datasets/genome/${r.accession}/`};
}
export async function searchNCBI(p) {
  const id = p.get('taxon_id'); if (!/^[1-9]\d*$/.test(id || '')) throw Error('Enter a numeric taxonomy ID.');
  const tax = await json(`/taxonomy/taxon/${id}/dataset_report`), t = tax.reports?.[0]?.taxonomy;
  if (!t) throw Error('NCBI taxonomy ID was not found.');
  const data = await json(`/genome/taxon/${id}/dataset_report`, {page_size: '25', tax_exact_match: p.get('exact') || 'false',
    'filters.assembly_source': p.get('source') || 'all', 'filters.assembly_version': p.get('versions') || 'current',
    'filters.search_text': p.get('q') || '', page_token: p.get('page_token') || ''});
  return {taxon: {id: t.tax_id, name: t.current_scientific_name?.name || '', rank: (t.rank || '').toLowerCase()},
    assemblies: (data.reports || []).map(summary), total: Number(data.total_count || 0), next_page_token: data.next_page_token || '', includes_descendants: p.get('exact') !== 'true'};
}
export async function downloadNCBI(accession, addInput) {
  if (!/^GC[AF]_\d{9}\.\d+$/.test(accession)) throw Error('Use a versioned NCBI assembly accession.');
  const report = await json(`/genome/accession/${accession}/dataset_report`);
  const matches = (report.reports || []).filter(r => r.accession === accession);
  if (matches.length !== 1) throw Error('NCBI did not return the requested version. No substitute was downloaded.');
  const meta = summary(matches[0]); if (meta.bases > MAX) throw Error('Genome exceeds the 50 MiB per-input limit.');
  const path = `/genome/accession/${accession}/download`, params = {include_annotation_type: 'GENOME_FASTA'};
  const archive = await fetchNCBI(path, params, 55 * 1024 * 1024);
  const chunks = []; let count = 0, size = 0, complete = false, failure;
  const unzip = new Unzip(file => {
    if (!file.name.startsWith(`ncbi_dataset/data/${accession}/`) || !file.name.endsWith('_genomic.fna')) return;
    count++;
    if (file.originalSize > MAX) { failure = Error('Downloaded FASTA exceeds 50 MiB.'); return; }
    file.ondata = (error, data, final) => {
      if (error) { failure = error; file.terminate(); return; }
      size += data.length;
      if (size > MAX) { failure = Error('Downloaded FASTA exceeds 50 MiB.'); file.terminate(); return; }
      chunks.push(data); if (final) complete = true;
    };
    file.start();
  });
  unzip.register(UnzipInflate);
  const reader = archive.stream().getReader();
  while (true) { const {value, done} = await reader.read(); unzip.push(value || new Uint8Array(), done); if (failure) throw failure; if (done) break; }
  if (count !== 1 || !complete) throw Error('Package must contain exactly one complete genomic FASTA for this assembly.');
  return addInput(new Blob(chunks), `${accession}.fna`, {...meta, provider: 'NCBI Datasets', downloaded_at: new Date().toISOString(), download_url: BASE + path + '?' + new URLSearchParams(params)});
}
