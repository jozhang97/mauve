import {Store, MemberCache} from './store.mjs';
import {parseXMFA, metadata, columnSlice, coordinateColumn, profileMember, basename} from './core.mjs';
import {parseRecords, annotationData, verifyMember} from './genbank.mjs';
import {Accelerator} from './gpu.mjs';
import {Jobs} from './jobs.mjs';
import {searchNCBI, downloadNCBI} from './ncbi.mjs';
const store = new Store(), ready = store.open(), cache = new MemberCache(store), accelerator = new Accelerator();
const jobs = new Jobs(store, importAlignment, () => self.postMessage({usage: 'alignment-completed'})), decoder = new TextDecoder(), profileCache = new Map();
const progress = message => self.postMessage({progress: message});
async function getAlignment(id) { const a = await store.get('alignments', id); if (!a) throw Error('Alignment not found.'); return a; }
async function getBlock(aid, bid) { await getAlignment(aid); const b = await store.get('blocks', [aid, bid]); if (!b) throw Error('Block not found.'); return b; }
async function importAlignment(blob, name, inputs) {
  if (!(blob instanceof Blob) || blob.size > 256 * 1024 * 1024) throw Error('Alignment files must be at most 256 MiB.');
  const id = crypto.randomUUID();
  try {
    const meta = await parseXMFA(blob, async block => {
      await store.batch([['blocks', [id, block.id], {...block, members: block.members.map(metadata)}], ...block.members.map(m => ['members', [id, block.id, m.genome_id], m])]);
      progress(`Importing block ${block.id}…`);
    });
    if (inputs) for (const g of meta.genomes) { if (!inputs[g.id - 1]) throw Error('Aligner output contains an unexpected genome ID.'); g.name = inputs[g.id - 1].name; }
    const alignment = {id, name: basename(name).slice(0, 200) || 'Untitled alignment', created: new Date().toISOString(), ...meta};
    await store.put('alignments', id, alignment); progress(''); return alignment;
  } catch (e) { await store.deleteAlignment(id); progress(''); throw e; }
}
async function importAnnotations(aid, gid, blob, name, concatenate) {
  const a = await getAlignment(aid); if (!a.genomes.some(g => g.id === gid)) throw Error('Genome not found.');
  if (blob.size > 50 * 1024 * 1024) throw Error('GenBank files must be at most 50 MiB.');
  const parsed = annotationData(await parseRecords(blob), concatenate); let verified = 0;
  for (const b of await store.all('blocks', store.range(aid))) if (b.members.some(m => m.genome_id === gid)) verified += verifyMember(await cache.get(aid, b.id, gid), parsed.sequence);
  if (!verified) throw Error('No unambiguous aligned bases are available to verify this GenBank sequence.');
  const metadata = {records: parsed.records, length: parsed.length, verified_bases: verified, feature_count: parsed.features.length};
  const features = parsed.features.map((f, i) => ({...f, id: `${gid}:${i}`, genome_id: gid})).sort((a, b) => a.start - b.start);
  await store.put('annotations', [aid, gid], {genome_id: gid, name: basename(name), metadata, features}); return metadata;
}
function integer(p, key, fallback, min = 0, max = Number.MAX_SAFE_INTEGER) {
  const n = p.has(key) ? Number(p.get(key)) : fallback;
  if (!Number.isSafeInteger(n) || n < min || n > max) throw Error(`Invalid ${key}.`); return n;
}
async function route(path, options = {}) {
  const u = new URL(path, 'https://local.invalid'), p = u.searchParams, parts = u.pathname.split('/').filter(Boolean), method = options.method || 'GET';
  if (parts[1] === 'capabilities') { await accelerator.ready; return {mode: accelerator.mode, adapter: accelerator.adapter, storage: await navigator.storage.estimate()}; }
  if (parts[1] === 'engine') return jobs.engine();
  if (parts[1] === 'inputs' && method === 'POST') return jobs.addInput(options.body, p.get('name') || 'genome.fasta');
  if (parts[1] === 'ncbi') return parts[3] ? downloadNCBI(parts[3], (...args) => jobs.addInput(...args)) : searchNCBI(p);
  if (parts[1] === 'jobs') {
    const id = parts[2];
    if (!id) return method === 'POST' ? jobs.create(JSON.parse(options.body)) : jobs.list();
    if (parts[3] === 'cancel') return jobs.cancel(id);
    if (parts[3] === 'import') return jobs.retry(id);
    if (parts[3] === 'artifacts') { const blob = await store.get('artifacts', [id, parts[4]]); if (!blob) throw Error('Artifact not found.'); return {blob, filename: ({xmfa: 'alignment.xmfa', tree: 'guide.tree', backbone: 'alignment.backbone', log: 'run.log', manifest: 'manifest.json'})[parts[4]]}; }
    return jobs.get(id);
  }
  if (parts[1] === 'demo') {
    let a = (await store.all('alignments')).find(a => a.name === 'Yeast demo');
    if (!a) a = await importAlignment(await (await fetch(new URL('../demo.alignment', import.meta.url))).blob(), 'Yeast demo');
    if (!await store.get('annotations', [a.id, 2])) await importAnnotations(a.id, 2, await (await fetch(new URL('../demo.gbk', import.meta.url))).blob(), 'Yeast demo annotations', true);
    return a;
  }
  if (parts[1] !== 'alignments') throw Error('Unknown operation.');
  const aid = parts[2];
  if (!aid) {
    if (method === 'POST') return importAlignment(options.body, p.get('name') || 'alignment.xmfa');
    return (await store.all('alignments')).sort((a, b) => b.created.localeCompare(a.created)).map(({genomes, ...a}) => a);
  }
  const alignment = await getAlignment(aid);
  if (parts.length === 3) return alignment;
  if (parts[3] === 'annotations') return (await store.all('annotations', store.range(aid))).map(({features, ...s}) => s);
  if (parts[3] === 'genomes') return importAnnotations(aid, Number(parts[4]), options.body, p.get('name') || 'annotations.gbk', p.get('concatenate') === 'true');
  if (parts[3] === 'features') {
    const start = integer(p, 'start', 1, 1), end = integer(p, 'end', Number.MAX_SAFE_INTEGER, start), offset = integer(p, 'offset', 0), limit = integer(p, 'limit', 100, 1, 500);
    const gid = p.has('genome_id') ? integer(p, 'genome_id', 0, 1) : null, query = (p.get('q') || '').toLowerCase();
    const sources = await store.all('annotations', store.range(aid)), items = []; let total = 0;
    for (const source of sources) {
      if (gid !== null && source.genome_id !== gid) continue;
      for (const f of source.features) {
        if (f.start > end) break;
        if (f.end < start || (query && ![f.name, f.type, f.locus_tag, f.product, f.note, f.record].join(' ').toLowerCase().includes(query))) continue;
        if (total++ >= offset && items.length < limit) items.push(f);
      }
    }
    return {total, items};
  }
  if (parts[3] === 'blocks.tsv') {
    const chunks = ['block_id\talignment_columns\tgenome_id\tstart_1based\tend_inclusive\tstrand\n'];
    for (const b of await store.all('blocks', store.range(aid))) for (const m of b.members) chunks.push([b.id, b.columns, m.genome_id, m.start, m.end, m.strand].join('\t') + '\n');
    return {blob: new Blob(chunks, {type: 'text/tab-separated-values'}), filename: 'alignment-blocks.tsv'};
  }
  if (parts[3] !== 'blocks') throw Error('Unknown alignment operation.');
  if (!parts[4]) return store.all('blocks', store.range(aid));
  const bid = Number(parts[4]), block = await getBlock(aid, bid);
  if (parts[5] === 'profile') {
    const ref = integer(p, 'reference_id', 0, 1), bins = integer(p, 'bins', 100, 1, 200), key = `${aid}/${bid}/${ref}/${bins}`;
    if (profileCache.has(key)) return profileCache.get(key);
    if (!block.members.some(m => m.genome_id === ref)) return {reference_id: ref, present: false, members: []};
    const reference = await cache.get(aid, bid, ref), width = Math.max(1, Math.ceil(block.columns / bins)), members = [];
    for (const info of block.members) if (info.genome_id !== ref) {
      const m = await cache.get(aid, bid, info.genome_id);
      members.push(profileMember(m, block.columns, width, await accelerator.counts(m.sequence, reference.sequence, width)));
    }
    const result = {reference_id: ref, present: true, members};
    if (profileCache.size >= 16) profileCache.delete(profileCache.keys().next().value); profileCache.set(key, result); return result;
  }
  if (parts[5] === 'next-difference') {
    const after = integer(p, 'after', 0), reference = await cache.get(aid, bid, block.members[0].genome_id); let first = block.columns;
    for (const info of block.members.slice(1)) {
      const m = await cache.get(aid, bid, info.genome_id);
      for (let i = after; i < first; i++) if (m.sequence[i] !== reference.sequence[i]) { first = i; break; }
      if (first === after) break;
    }
    return {offset: first < block.columns ? first : null};
  }
  if (parts[5] === 'fasta') {
    const chunks = [];
    for (const info of block.members) {
      const m = await cache.get(aid, bid, info.genome_id);
      chunks.push(`>sequence_${m.genome_id} block=${bid} coordinates=${m.start}-${m.end} strand=${m.strand}\n`);
      for (let start = 0; start < m.sequence.length; start += 81920) {
        const lines = [];
        for (let i = start; i < Math.min(start + 81920, m.sequence.length); i += 80) lines.push(decoder.decode(m.sequence.subarray(i, i + 80)));
        chunks.push(lines.join('\n') + '\n');
      }
    }
    return {blob: new Blob(chunks, {type: 'text/plain'}), filename: `block-${bid}.fasta`};
  }
  let offset = integer(p, 'offset', 0), limit = integer(p, 'limit', 100, 1, 500);
  if (p.has('position') !== p.has('genome_id')) throw Error('Provide both a genome ID and genomic position.');
  if (p.has('position')) offset = coordinateColumn(await cache.get(aid, bid, integer(p, 'genome_id', 0, 1)), integer(p, 'position', 1, 1));
  if (offset >= block.columns) throw Error('Column offset is outside this block.');
  const members = [];
  for (const m of block.members) members.push(columnSlice(await cache.get(aid, bid, m.genome_id), offset, limit));
  return {id: bid, columns: block.columns, offset, members};
}
// Serialize API operations to bound simultaneous reads/compute and GPU resources.
// The aligner has its own worker, so queries and cancellation remain available.
let queue = Promise.resolve();
ready.catch(() => {});
self.onmessage = ({data: {id, path, options}}) => {
  queue = queue.then(async () => {
    try { await ready; self.postMessage({id, result: await route(path, options)}); }
    catch (error) { self.postMessage({id, error: error.name === 'QuotaExceededError' ? 'Browser storage is full. Export your work and free space before importing again.' : error.message || String(error)}); }
  });
};
