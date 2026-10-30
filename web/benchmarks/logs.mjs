// Compare real Jobs.run log handling with an in-memory store (no IndexedDB I/O).
import {readFile, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {setImmediate} from 'node:timers/promises';
const [baseline, candidate, output] = process.argv.slice(2);
if (!output) throw Error('Usage: node --expose-gc logs.mjs BASELINE_JOBS CANDIDATE_JOBS OUTPUT');
const base = pathToFileURL(resolve(candidate));
async function load(path) {
  const source = (await readFile(path, 'utf8')).replaceAll('import.meta.url', JSON.stringify(base.href)).replace(/from '(\.\/[^']+)'/g, (_, relative) => `from '${new URL(relative, base)}'`);
  return (await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))).Jobs;
}
const engines = {baseline: await load(baseline), candidate: await load(candidate)};
const source_sha256 = Object.fromEntries(await Promise.all(Object.entries({baseline, candidate}).map(async ([name, path]) => [name, createHash('sha256').update(await readFile(path)).digest('hex')])));
const report = {source_sha256, node: process.version, measured_at: new Date().toISOString(), description: 'Jobs.run, fake worker, in-memory store, 4096-character log messages; includes final Blob and excludes artifact hashing', cases: []};
for (const bytes of [1024 * 1024, 8 * 1024 * 1024]) {
  const chunks = Array.from({length: bytes / 4096}, (_, i) => String(i).padStart(8, '0') + 'ACGT'.repeat(1022));
  const expected = chunks.join('');
  const runs = {baseline: [], candidate: []};
  for (let repeat = 0; repeat < 3; repeat++) for (const name of repeat % 2 ? ['candidate', 'baseline'] : ['baseline', 'candidate']) {
    global.gc?.();
    let artifact;
    const store = {
      async put() {}, async get() {},
      async batch(rows) { for (const [table, key, value] of rows) if (table === 'artifacts' && key[1] === 'log') artifact = value; },
    };
    global.Worker = class {
      postMessage() { queueMicrotask(async () => {
        for (const text of chunks) {
          this.onmessage({data: {type: 'log', text}});
          await setImmediate();
        }
        this.onmessage({data: {type: 'done', files: {xmfa: new Blob(['alignment'])}}});
      }); }
      terminate() {}
    };
    const jobs = new engines[name](store, async () => ({id: 'result'}));
    const job = {id: 'bench', log: '', artifacts: ['manifest'], spec: {command: []}};
    jobs.running.set(job.id, {cancelled: false});
    const start = performance.now();
    await jobs.run(job, []);
    const ms = performance.now() - start;
    assert.equal(job.status, 'succeeded');
    assert.equal(job.log, expected.slice(-32768));
    assert.equal(await artifact.text(), expected);
    runs[name].push(ms);
  }
  const median = x => [...x].sort((a, b) => a - b)[1];
  report.cases.push({bytes, runs_ms: runs, speedup: median(runs.baseline) / median(runs.candidate), artifact_sha256: createHash('sha256').update(expected).digest('hex')});
  console.log(JSON.stringify(report.cases.at(-1)));
}
await writeFile(output, JSON.stringify(report, null, 2) + '\n');
