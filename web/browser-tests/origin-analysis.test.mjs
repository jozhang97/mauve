import {test} from 'node:test';
import assert from 'node:assert/strict';
import '../mauve_web/static/replication.js';
import {analyzeOrigins,histogram,midpoint,chromosomeOrientations,circularMean,maximumCircularSeparation} from '../mauve_web/static/browser/origin-analysis.mjs';
test('midpoints follow compound and reverse annotation segments through origin',()=>{
  assert.equal(midpoint({parts:[{start:91,end:100,strand:'+'},{start:1,end:10,strand:'+'}]}),1);
  assert.equal(midpoint({parts:[{start:1,end:10,strand:'-'},{start:91,end:100,strand:'-'}]}),100);
  assert.equal(midpoint({order:91,strand:'+',parts:[{start:1,end:10,strand:'+'},{start:91,end:100,strand:'+'}]}),1);
  assert.equal(midpoint({order:91,strand:'-',parts:[{start:1,end:10,strand:'-'},{start:91,end:100,strand:'-'}]}),100);
});
test('distances, missing origins, duplicated family means, and core denominator',()=>{
  const genomes=[1,2,3].map(id=>({id,name:String(id)}));
  const sources=genomes.map(g=>({genome_id:g.id,metadata:{records:[{name:'chr',start:1,end:g.id===2?200:100,topology:'circular',replication_origin:g.id===3?null:1}]}}));
  const gene=(id,start,end,strand='+')=>({genome_id:id,record:'chr',parts:[{start,end,strand}],strand});
  const result={genomes,families:[{id:'core',genomes:3,members:[gene(1,10,12),gene(2,20,22),gene(2,60,62),gene(3,10,12)]},{id:'accessory',genomes:1,members:[gene(1,90,92,'-')]}]};
  const out=analyzeOrigins(result,sources,genomes,globalThis.mauveReplication);
  assert.deepEqual(out.eligible,[1,2]);assert.equal(out.excluded.length,1);
  assert.equal(out.genes.filter(g=>g.category==='core').length,3);
  assert.equal(out.genes.at(-1).distance_bp,10);
  assert.equal(out.ranges.length,1);assert.equal(out.ranges[0].range_bp,30);
  assert.ok(Math.abs(out.ranges[0].range_fraction-0.1)<1e-10);
  assert.equal(out.ranges[0].duplicated,true);
});
test('histogram includes zero and terminal boundary and preserves empty bins',()=>{
  const bins=histogram([0,0.5,1,null,NaN],1,2);
  assert.deepEqual(bins.map(b=>b.count),[1,2]);
});
test('orientation normalization separates reverse complements from real arm disagreement',()=>{
  const genomes=[1,2,3].map(id=>({id,name:String(id)}));
  const sources=genomes.map(g=>({genome_id:g.id,metadata:{records:[{name:'chr',start:1,end:100,topology:'circular',replication_origin:1}]}}));
  const blocks=[{columns:100,members:[{genome_id:1,strand:'+'},{genome_id:2,strand:'-'},{genome_id:3,strand:'+'}]}];
  const gene=(genome_id,start,strand='+')=>({genome_id,record:'chr',parts:[{start,end:start+2,strand}],strand});
  const families=[{id:'stable',genomes:3,members:[gene(1,20),gene(2,80,'-'),gene(3,20)]},
    {id:'switch',genomes:3,members:[gene(1,20),gene(2,80,'-'),gene(3,80)]},
    {id:'boundary',genomes:3,members:[gene(1,1),gene(2,49,'-'),gene(3,1)]}];
  const out=analyzeOrigins({genomes,families},sources,genomes,globalThis.mauveReplication,{blocks,reference:1});
  assert.ok(out.ranges[0].position_range_fraction<1e-12);
  assert.ok(Math.abs(out.ranges[1].position_range_fraction-0.4)<1e-12);
  assert.equal(out.ranges[2].position_genomes,3);
  const ambiguous=chromosomeOrientations(genomes,[...blocks,{columns:90,members:[{genome_id:1,strand:'+'},{genome_id:2,strand:'+'}]}],1);
  assert.equal(ambiguous[1].direction,null);
});
test('duplicate copies use a circular mean per genome',()=>{
  const genomes=[1,2].map(id=>({id,name:String(id)}));
  const sources=genomes.map(g=>({genome_id:g.id,metadata:{records:[{name:'chr',start:1,end:100,topology:'circular',replication_origin:1}]}}));
  const gene=(genome_id,start)=>({genome_id,record:'chr',parts:[{start,end:start+2,strand:'+'}]});
  const result={genomes,families:[{id:'duplicate',genomes:2,members:[gene(1,20),gene(2,20),gene(2,80)]}]};
  const out=analyzeOrigins(result,sources,genomes,globalThis.mauveReplication,{reference:1,blocks:[{columns:100,members:[{genome_id:1,strand:'+'},{genome_id:2,strand:'+'}]}]});
  assert.equal(out.ranges[0].position_genomes,2);
  assert.ok(Math.abs(out.ranges[0].position_range_fraction-0.2)<1e-12);
});
test('pairwise separation wraps at oriC and terminus without arm-boundary exclusion',()=>{
  assert.ok(Math.abs(maximumCircularSeparation([0.2,0.22])-0.02)<1e-12);
  assert.ok(Math.abs(maximumCircularSeparation([0.2,0.8])-0.4)<1e-12);
  assert.ok(Math.abs(maximumCircularSeparation([0.49,0.51])-0.02)<1e-12);
  assert.ok(Math.abs(maximumCircularSeparation([0.99,0.01])-0.02)<1e-12);
  assert.equal(maximumCircularSeparation([0,0.5]),0.5);
  assert.equal(maximumCircularSeparation([0]),null);
  assert.equal(circularMean([0,0.5]),null);
  const mean=circularMean([0.99,0.01]);assert.ok(mean<1e-12||mean>1-1e-12);
});
test('essential family ranges retain family evidence without assigning it to unmatched gene copies',()=>{
  const genomes=[1,2].map(id=>({id,name:String(id)}));
  const sources=genomes.map(g=>({genome_id:g.id,metadata:{records:[{name:'chr',start:1,end:100,topology:'circular',replication_origin:1}]}}));
  const members=genomes.map(g=>({genome_id:g.id,record:'chr',strand:'+',parts:[{start:20,end:30,strand:'+'}],essentiality:{status:g.id===1?'essential':'unknown'}}));
  const result={genomes,families:[{id:'F1',genomes:2,essentiality:{status:'essential'},members}]};
  const out=analyzeOrigins(result,sources,genomes,globalThis.mauveReplication,{reference:1,blocks:[{columns:100,members:[{genome_id:1,strand:'+'},{genome_id:2,strand:'+'}]}]});
  assert.equal(out.ranges[0].essential_reference,true);
  assert.equal(out.ranges[0].reference_essentiality,'essential');
  assert.equal(out.ranges[0].position_genomes,2);
  assert.equal(out.genes.filter(g=>g.essentiality.status==='essential').length,1);
  assert.equal(out.genes[1].essentiality.status,'unknown');
});
