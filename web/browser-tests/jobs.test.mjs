import test from 'node:test';
import assert from 'node:assert/strict';
import {Jobs} from '../mauve_web/static/browser/jobs.mjs';

function mockWorker(t, Worker) {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'Worker');
  Object.defineProperty(globalThis, 'Worker', {value: Worker, configurable: true});
  t.after(() => { if (original) Object.defineProperty(globalThis, 'Worker', original); else delete globalThis.Worker; });
}

function setup(failLog = false) {
  const saved = new Map();
  const store = {
    async put(name, id, value) {
      if (failLog && name === 'jobs' && value.log) { failLog = false; throw Error('Log storage unavailable'); }
      saved.set(`${name}/${id}`, structuredClone(value));
    },
    async get(name, id) { return saved.get(`${name}/${id}`); },
    async batch(rows) { for (const [name, id, value] of rows) await this.put(name, id, value); },
  };
  const jobs = new Jobs(store, () => { throw Error('Unexpected import'); });
  const job = {id: 'test', status: 'queued', log: '', artifacts: ['manifest'], spec: {command: []}};
  jobs.running.set(job.id, {cancelled: false});
  return {jobs, job, saved};
}

test('native exception builds report an actionable error in unsupported runtimes', async t => {
  const original = globalThis.WebAssembly;
  t.after(() => { globalThis.WebAssembly = original; });
  const {jobs} = setup();
  jobs.engineInfo = Promise.resolve({configuration: {exceptions: 'wasm'}});
  assert.equal((await jobs.engine()).available, true);
  globalThis.WebAssembly = {};
  const info = await jobs.engine();
  assert.equal(info.available, false);
  assert.match(info.reason, /Update your browser/);
});

test('worker startup failure persists a terminal job and releases resources', async t => {
  mockWorker(t, function () { throw Error('Worker startup failed'); });
  const {jobs, job, saved} = setup();
  await jobs.run(job, []);
  assert.equal(saved.get('jobs/test').status, 'failed');
  assert.equal(saved.get('jobs/test').error, 'Worker startup failed');
  assert.ok(saved.get('jobs/test').finished);
});

test('failed log write stops the worker and cannot overwrite the terminal status', async t => {
  let terminated = false;
  mockWorker(t, class {
    postMessage() { queueMicrotask(() => this.onmessage({data: {type: 'log', text: 'progress'}})); }
    terminate() { terminated = true; }
  });
  const {jobs, job, saved} = setup(true);
  await jobs.run(job, []);
  assert.equal(saved.get('jobs/test').status, 'failed');
  assert.equal(saved.get('jobs/test').error, 'Log storage unavailable');
  assert.ok(terminated);
});

test('completion notification occurs once, after the successful result is persisted', async t => {
  let terminated = false;
  mockWorker(t, class {
    postMessage() { queueMicrotask(() => this.onmessage({data: {type: 'done', files: {xmfa: new Blob(['alignment'])}}})); }
    terminate() { terminated = true; }
  });
  const {jobs, job, saved} = setup();
  let completed = 0;
  jobs.importer = async blob => {
    assert.ok(terminated, 'release engine memory before importing results');
    assert.equal(jobs.running.get(job.id).worker, null);
    assert.equal(await blob.text(), 'alignment');
    return {id: 'saved-result'};
  };
  jobs.onComplete = () => { assert.equal(saved.get('jobs/test').status, 'succeeded'); completed++; };
  await jobs.run(job, []);
  await jobs.get(job.id);
  await jobs.get(job.id);
  assert.equal(completed, 1);
  assert.equal(saved.get('jobs/test').alignment_id, 'saved-result');
});

for (const exceed of [false, true]) test(`chunked logs preserve full artifact and bounded tail (${exceed ? 'limit' : 'success'})`, async t => {
  const chunks = exceed ? ['x'.repeat(25 * 1024 * 1024), 'overflow'] :
    ['start\n', ...Array.from({length: 48}, (_, i) => `${i}:` + 'ACGT'.repeat(1024) + '\n'), '\ud83e', '\uddec\n'];
  mockWorker(t, class {
    postMessage() {
      queueMicrotask(() => {
        for (const text of chunks) this.onmessage({data: {type: 'log', text}});
        this.onmessage({data: {type: 'done', files: {xmfa: new Blob(['alignment'])}}});
      });
    }
    terminate() {}
  });
  const {jobs, job, saved} = setup();
  jobs.importer = async () => ({id: 'result'});
  await jobs.run(job, []);
  const full = chunks.join('');
  assert.equal(await saved.get('artifacts/test,log').text(), full);
  assert.equal(job.log, (exceed ? chunks[0] : full).slice(-32768));
  assert.equal(job.log_truncated, true);
  assert.equal(job.status, exceed ? 'failed' : 'succeeded');
  if (exceed) assert.match(job.error, /25 MiB log limit/);
});
