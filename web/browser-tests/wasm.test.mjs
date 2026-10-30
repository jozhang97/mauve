import test from 'node:test';
import assert from 'node:assert/strict';
import createMauve from '../mauve_web/static/wasm/progressiveMauve.mjs';
import {parseXMFA} from '../mauve_web/static/browser/core.mjs';
import {stageInputs} from '../mauve_web/static/browser/aligner-inputs.mjs';
function sequence(n) { let state = 12345, out = ''; for (let i=0;i<n;i++) { state=(Math.imul(state,1664525)+1013904223)>>>0; out+='ACGT'[state>>>30]; } return out; }
test('real WebAssembly progressiveMauve aligns twelve genomes', async () => {
  const m = await createMauve({noInitialRun: true, print: () => {}, printErr: () => {}}), original = sequence(5000), paths=[];
  for (let i=0;i<12;i++) { const path=`/input-${i}.fa`;paths.push(path); const at=100+i*100; m.FS.writeFile(path, '>genome\n'+original.slice(0,at)+'A'+original.slice(at+1)+'\n'); }
  assert.equal(m.callMain(['--output=/alignment.xmfa','--output-guide-tree=/guide.tree',...paths]), 0);
  const blocks = [], meta=await parseXMFA(new Blob([m.FS.readFile('/alignment.xmfa')]), b => blocks.push(b));
  assert.equal(meta.genomes.length, 12); assert.ok(meta.genomes.every(g=>g.extent===5000));
  assert.ok(blocks.some(b=>b.members.length===12)); assert.ok(m.FS.readFile('/guide.tree').length>0);
});

test('owned input staging preserves real alignment results and source Blobs', async () => {
  const original = sequence(5000);
  const inputs = [new Blob(['>first\n', original, '\n']),
    new Blob(['>second\n', original.slice(0, 1500), 'A', original.slice(1501), '\n'])];
  const results = [];
  for (const owned of [false, true]) {
    const m = await createMauve({noInitialRun: true, print: () => {}, printErr: () => {}});
    if (owned) await stageInputs(m, inputs);
    else for (let i = 0; i < inputs.length; i++) {
      m.FS.writeFile(`/input-${i + 1}.fa`, new Uint8Array(await inputs[i].arrayBuffer()));
    }
    assert.equal(m.callMain(['--output=/alignment.xmfa', '--output-guide-tree=/guide.tree',
      '/input-1.fa', '/input-2.fa']), 0);
    results.push([m.FS.readFile('/alignment.xmfa'), m.FS.readFile('/guide.tree')]);
  }
  assert.deepEqual(results[1], results[0]);
  assert.equal(await inputs[0].text(), '>first\n' + original + '\n');
});
