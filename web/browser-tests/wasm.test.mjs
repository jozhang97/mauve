import test from 'node:test';
import assert from 'node:assert/strict';
import createMauve from '../mauve_web/static/wasm/progressiveMauve.mjs';
import {parseXMFA} from '../mauve_web/static/browser/core.mjs';
function sequence(n) { let state = 12345, out = ''; for (let i=0;i<n;i++) { state=(Math.imul(state,1664525)+1013904223)>>>0; out+='ACGT'[state>>>30]; } return out; }
test('real WebAssembly progressiveMauve aligns twelve genomes', async () => {
  const m = await createMauve({noInitialRun: true, print: () => {}, printErr: () => {}}), original = sequence(5000), paths=[];
  for (let i=0;i<12;i++) { const path=`/input-${i}.fa`;paths.push(path); const at=100+i*100; m.FS.writeFile(path, '>genome\n'+original.slice(0,at)+'A'+original.slice(at+1)+'\n'); }
  assert.equal(m.callMain(['--output=/alignment.xmfa','--output-guide-tree=/guide.tree',...paths]), 0);
  const blocks = [], meta=await parseXMFA(new Blob([m.FS.readFile('/alignment.xmfa')]), b => blocks.push(b));
  assert.equal(meta.genomes.length, 12); assert.ok(meta.genomes.every(g=>g.extent===5000));
  assert.ok(blocks.some(b=>b.members.length===12)); assert.ok(m.FS.readFile('/guide.tree').length>0);
});
