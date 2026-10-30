import {alignerConfig} from './aligner-config.mjs';
import {normalizeInput} from './genbank.mjs';
import {basename} from './core.mjs';
export const MAX_GENOMES = 64, MAX_BASES = 100000000, MAX_INPUT = 50 * 1024 * 1024;
const now = () => new Date().toISOString();
const hash = async blob => [...new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer()))].map(x => x.toString(16).padStart(2, '0')).join('');
export class Jobs {
  constructor(store, importer, onComplete = () => {}) { this.onComplete = onComplete; this.store = store; this.importer = importer; this.running = new Map(); }
  async engine() {
    const config = alignerConfig();
    this.engineInfo ||= fetch(new URL(`../${config.directory}/SOURCES.json`, import.meta.url)).then(r => { if (!r.ok) throw Error('Engine manifest is missing. Rebuild the static site.'); return r.json(); });
    const source = await this.engineInfo;
    const hasWasm = typeof WebAssembly !== 'undefined';
    const hasExceptions = hasWasm && (source.configuration?.exceptions !== 'wasm' || typeof WebAssembly.Exception === 'function');
    return {available: hasExceptions, threads: config.threads, version: `progressiveMauve · WebAssembly SIMD (${config.threads} thread${config.threads === 1 ? '' : 's'}, local)`,
      reason: hasWasm ? 'Update your browser to run the aligner with WebAssembly exception support.' : 'This browser needs WebAssembly support.', max_genomes: MAX_GENOMES, source};
  }
  async addInput(blob, name, provenance = null) {
    if (blob.size > MAX_INPUT) throw Error('Each input must be at most 50 MiB.');
    const {normalized, ...meta} = await normalizeInput(blob);
    const id = crypto.randomUUID(), input = {id, name: basename(name), ...meta, provenance,
      original_sha256: await hash(blob), normalized_sha256: await hash(normalized)};
    await this.store.put('inputs', id, {...input, normalized}); return input;
  }
  async list() {
    const jobs = (await this.store.all('jobs')).sort((a, b) => b.created.localeCompare(a.created));
    // A tab owns each job's lock while it is running. Reloaded/closed tabs release it.
    for (const job of jobs) if (['running', 'queued', 'importing'].includes(job.status) && !this.running.has(job.id)) {
      await navigator.locks.request('mauve-job-' + job.id, {ifAvailable: true}, async lock => {
        if (lock) { const latest = await this.store.get('jobs', job.id); if (['running', 'queued', 'importing'].includes(latest.status)) { job.status = 'interrupted'; job.error = 'The tab running this job was closed. Rerun with the saved inputs.'; await this.store.put('jobs', job.id, {...latest, status: job.status, error: job.error}); } }
      });
    }
    return jobs;
  }
  async get(id) { const j = await this.store.get('jobs', id); if (!j) throw Error('Job not found.'); return j; }
  async create(options) {
    if (!navigator.locks) throw Error('This browser needs Web Locks to run local jobs safely.');
    const engine = await this.engine();
    if (!engine.available) throw Error(engine.reason);
    const ids = options.input_ids;
    if (!Array.isArray(ids) || ids.length < 2 || ids.length > MAX_GENOMES || new Set(ids).size !== ids.length) throw Error(`Choose 2–${MAX_GENOMES} different genome inputs.`);
    if (options.min_weight != null && (!Number.isInteger(options.min_weight) || options.min_weight < 0 || options.min_weight > 1e9)) throw Error('Invalid minimum LCB score.');
    const inputs = [];
    for (const id of ids) { const i = await this.store.get('inputs', id); if (!i) throw Error('Input not found.'); inputs.push(i); }
    if (inputs.reduce((n, i) => n + i.bases, 0) > MAX_BASES) throw Error('Inputs exceed the current 100 million base memory budget.');
    if (!options.concatenate_records && inputs.some(i => i.records.length > 1)) throw Error('Enable record concatenation for multi-record inputs.');
    const command = ['--output=/alignment.xmfa', '--output-guide-tree=/guide.tree', '--backbone-output=/alignment.backbone'];
    if (options.collinear) command.push('--collinear'); if (options.seed_family) command.push('--seed-family');
    if (options.min_weight != null) command.push(`--weight=${options.min_weight}`);
    command.push(...inputs.map((_, i) => `/input-${i + 1}.fa`));
    const job = {id: crypto.randomUUID(), name: (options.name || 'New alignment').slice(0, 200), created: now(), status: 'queued', log: '', log_truncated: false, error: '', artifacts: ['manifest'],
      spec: {options, command, engine: {version: engine.version, threads: engine.threads, ...engine.source}, inputs: inputs.map(({normalized, ...i}) => i)}};
    // Claim ownership before publishing so other tabs cannot mark a queued job interrupted.
    await new Promise((resolve, reject) => {
      navigator.locks.request('mauve-job-' + job.id, async () => {
        try {
          this.running.set(job.id, {cancelled: false, worker: null});
          await this.store.batch([['jobs', job.id, job], ['artifacts', [job.id, 'manifest'], new Blob([JSON.stringify(job.spec, null, 2)], {type: 'application/json'})]]);
          resolve(job);
          await navigator.locks.request('mauve-aligner', async () => { await this.run(job, inputs); });
        } catch (e) { reject(e); }
        finally { this.running.delete(job.id); }
      }).catch(reject);
    });
    return job;
  }
  async run(job, inputs) {
    const run = this.running.get(job.id); if (run.cancelled) return;
    let worker, logLength = 0, pending = Promise.resolve();
    const logChunks = [];
    const writeLog = text => {
      logChunks.push(text); logLength += text.length;
      if (logLength > 25 * 1024 * 1024) throw Error('Alignment exceeded the 25 MiB log limit.');
      job.log = (job.log + text).slice(-32768); job.log_truncated = logLength > 32768;
      const snapshot = {...job};
      pending = pending.then(() => this.store.put('jobs', job.id, snapshot)).catch(error => { run.reject?.(error); });
    };
    try {
      job.status = 'running'; job.started = now(); await this.store.put('jobs', job.id, job);
      worker = new Worker(new URL('./aligner-worker.mjs', import.meta.url), {type: 'module'}); run.worker = worker;
      const files = await new Promise((resolve, reject) => {
        run.reject = reject;
        worker.onerror = event => reject(Error(event.message));
        worker.onmessage = ({data}) => {
          try {
            if (data.type === 'log') writeLog(data.text);
            else if (data.type === 'done') resolve(data.files);
            else if (data.type === 'error') reject(Error(data.error));
          } catch (e) { reject(e); }
        };
        worker.postMessage({inputs: inputs.map(i => i.normalized), command: job.spec.command, threads: job.spec.engine?.threads ?? 1});
      });
      // The returned Blobs outlive the worker. Release the engine heap and
      // scratch filesystem before result parsing creates another large working set.
      worker.terminate(); run.worker = null; worker = null;
      await pending;
      if (run.cancelled) throw Error('Cancelled.');
      job.status = 'importing';
      job.artifacts = ['manifest', 'log', ...Object.keys(files)];
      await this.store.batch([['jobs', job.id, job], ...Object.entries(files).map(([k, v]) => ['artifacts', [job.id, k], v])]);
      const alignment = await this.importer(files.xmfa, job.name, job.spec.inputs);
      job.alignment_id = alignment.id; job.status = 'succeeded';
    } catch (e) { job.status = run.cancelled ? 'cancelled' : 'failed'; job.error = e.message || String(e); job.can_import_result = !run.cancelled && Boolean(await this.store.get('artifacts', [job.id, 'xmfa'])); }
    finally {
      worker?.terminate(); await pending;
      job.finished = now(); if (!job.artifacts.includes('log')) job.artifacts.push('log');
      await this.store.batch([['jobs', job.id, job], ['artifacts', [job.id, 'log'], new Blob([logChunks.join('')])]]);
      if (job.status === 'succeeded') this.onComplete();
    }
  }
  async cancel(id) {
    const run = this.running.get(id), job = await this.get(id);
    if (job.status === 'importing') throw Error('Import is already completing; wait for the result.');
    if (!run) throw Error('Cancel this job from the tab that started it.');
    run.cancelled = true; run.worker?.terminate(); run.reject?.(Error('Cancelled.'));
    if (job.status === 'queued') { job.status = 'cancelled'; job.finished = now(); await this.store.put('jobs', id, job); }
    return job;
  }
  async retry(id) {
    const job = await this.get(id); if (!job.can_import_result) throw Error('No saved result is available to import.');
    const a = await this.importer(await this.store.get('artifacts', [id, 'xmfa']), job.name, job.spec.inputs);
    job.alignment_id = a.id; job.status = 'succeeded'; job.error = ''; job.can_import_result = false; await this.store.put('jobs', id, job); return job;
  }
}
