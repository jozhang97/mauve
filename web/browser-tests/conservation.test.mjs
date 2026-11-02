import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {buildConservation, parseBackbone, sampleConservation} from '../mauve_web/static/browser/conservation.mjs';
const fixture = JSON.parse(readFileSync(new URL('./fixtures/conservation-java.json', import.meta.url)));
for (const c of fixture.cases) test(`Java conservation parity: ${c.name}`, async () => {
  const members = c.rows.map((row, i) => ({genome_id: i+1, start:1, end:row.replaceAll('-', '').length, strand:c.reverse?.includes(i)?'-':'+', sequence:new TextEncoder().encode(row)})).filter(m => m.end);
  const genomes = c.rows.map((row, i) => ({id:i+1, extent:Math.max(40,row.replaceAll('-', '').length)}));
  // Absent rows still count as genomes, as in the Java XMFA adapter.
  for (const m of members) genomes[m.genome_id-1].extent = m.end;
  const block = {id:1, columns:c.rows[0].length, members};
  const backbone = c.backbone ? [{block_id:1,left:0,right:block.columns,genomes:c.backbone.map(i=>i+1)}] : null;
  const indexes = await buildConservation(genomes, [block], async b=>b, backbone);
  for (let i=0;i<c.expected.length;i++) {
    const expected=c.expected[i]; if (!expected) continue;
    const hist=indexes.get(i+1).histogram;
    assert.equal(hist.levels[0].mean.length, expected.base.length);
    for (let j=0;j<expected.base.length;j++) assert.equal(hist.levels[0].mean[j], expected.base[j], `genome ${i+1} base ${j}`);
    for(const [left,right,mean,min,max] of expected.queries) assert.deepEqual([0,-1,1].map(type=>hist.value(left,right,type)),[mean,min,max],`genome ${i+1} range ${left}-${right}`);
  }
});
test('short blocks, inversion, backbone validation and bounded requests', async () => {
  const genomes=[{id:1,extent:4},{id:2,extent:4}];
  const block={id:1,columns:4,members:genomes.map(g=>({genome_id:g.id,start:1,end:4,strand:g.id===1?'+':'-',sequence:new TextEncoder().encode('AAAA')}))};
  const indexes=await buildConservation(genomes,[block],async b=>b);
  const result=sampleConservation(indexes,genomes.map(g=>({genome_id:g.id,start:1,end:4,bins:4})));
  assert.deepEqual(result[0].samples,result[1].samples);
  assert.ok(result[0].samples.every(s=>s.every(Number.isFinite)));
  assert.throws(()=>sampleConservation(indexes,[{genome_id:1,start:1,end:4,bins:99999}]));
  assert.throws(()=>parseBackbone('0 1 5 0 1',[block],genomes));
  assert.deepEqual(parseBackbone('0 1 4 0 1',[block],genomes),[{block_id:1,left:0,right:4,genomes:[1,2]}]);
});
test('overlapping backbone columns may describe disjoint strain groups', async () => {
  const rows=['AAAAA'.repeat(8),'AAAAA'.repeat(8),'CCCCC'.repeat(8),'TTTTT'.repeat(8)];
  const genomes=rows.map((_,i)=>({id:i+1,extent:40}));
  const block={id:1,columns:40,members:rows.map((row,i)=>({genome_id:i+1,start:1,end:40,strand:'+',sequence:new TextEncoder().encode(row)}))};
  const bb=parseBackbone('0 1 40 0 1\n0 1 40 2 3',[block],genomes);
  const indexes=await buildConservation(genomes,[block],async b=>b,bb);
  assert.equal(indexes.get(1).histogram.value(1,40),127);
  assert.equal(indexes.get(3).histogram.value(1,40),-128);
  assert.throws(()=>parseBackbone('0 1 40 0 1\n0 1 40 1 2',[block],genomes));
});
test('genome-anchored bins span block boundaries and retain missing-genome penalties', async () => {
  const genomes=[{id:1,extent:20},{id:2,extent:20}];
  const make=(id,start,rows)=>({id,columns:rows[0].length,members:rows.map((row,i)=>({genome_id:i+1,start,end:start+row.length-1,strand:'+',sequence:new TextEncoder().encode(row)}))});
  const whole=make(1,1,['A'.repeat(20),'A'.repeat(7)+'T'.repeat(13)]);
  const parts=[make(1,1,['A'.repeat(7),'A'.repeat(7)]),make(2,8,['A'.repeat(13),'T'.repeat(13)])];
  const a=await buildConservation(genomes,[whole],async b=>b), b=await buildConservation(genomes,parts,async b=>b);
  for (const g of genomes) assert.deepEqual(a.get(g.id).histogram.levels[0].mean,b.get(g.id).histogram.levels[0].mean);
});
