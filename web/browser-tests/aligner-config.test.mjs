import test from 'node:test';
import assert from 'node:assert/strict';
import {alignerConfig} from '../mauve_web/static/browser/aligner-config.mjs';

test('thread selection requires isolation and shared memory, caps automatic concurrency', () => {
  const scope = {crossOriginIsolated:true, SharedArrayBuffer, navigator:{hardwareConcurrency:16}};
  assert.deepEqual(alignerConfig(scope), {threads:8, directory:'wasm-threaded', threaded:true});
  assert.equal(alignerConfig({...scope, crossOriginIsolated:false}, 8).threads, 1);
  assert.equal(alignerConfig({...scope, SharedArrayBuffer:undefined}, 8).directory, 'wasm');
  assert.equal(alignerConfig(scope, 1).threaded, false);
  assert.equal(alignerConfig(scope, 16).threads, 16);
  for (const n of [0,17,1.5,NaN,'8']) assert.throws(()=>alignerConfig(scope,n));
});
