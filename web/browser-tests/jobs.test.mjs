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
  mockWorker(t, class {
    postMessage() { queueMicrotask(() => this.onmessage({data: {type: 'done', files: {xmfa: new Blob(['alignment'])}}})); }
    terminate() {}
  });
  const {jobs, job, saved} = setup();
  let completed = 0;
  jobs.importer = async () => ({id: 'saved-result'});
  jobs.onComplete = () => { assert.equal(saved.get('jobs/test').status, 'succeeded'); completed++; };
  await jobs.run(job, []);
  await jobs.get(job.id);
  await jobs.get(job.id);
  assert.equal(completed, 1);
  assert.equal(saved.get('jobs/test').alignment_id, 'saved-result');
});
