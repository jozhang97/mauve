import test from 'node:test';
import assert from 'node:assert/strict';
import geometry from '../mauve_web/static/track-geometry.js';
const {base,edge,interval,copies,directions,coreIndex} = geometry;

test('reverse base coordinates round-trip at every base, including chromosome ends', () => {
  for (const extent of [1,2,37,2000]) for (let p=1;p<=extent;p++) {
    assert.equal(base(base(p,extent,-1),extent,-1),p);
    assert.equal(base(p,extent,1),p);
    assert.equal(base(p,extent,-1)+p,extent+1);
  }
});

test('half-open drawing edges contain the same inclusive bases on both strands', () => {
  for (const direction of [1,-1]) for (const [start,end] of [[1,1],[1,37],[37,37],[8,19]]) {
    const bounds=[edge(start,37,direction),edge(end+1,37,direction)].sort((a,b)=>a-b);
    assert.equal(bounds[1]-bounds[0],end-start+1);
    assert.deepEqual(interval(start,end,37,direction),[bounds[0],bounds[1]-1]);
    for(let p=start;p<=end;p++) assert.ok(base(p,37,direction)>=bounds[0]&&base(p,37,direction)<bounds[1]);
  }
});

test('circular copies cover one chromosome without duplicate native bases across the origin', () => {
  const length=37;
  for (const direction of [1,-1]) for(const offset of [-83,-37,-1,0,12,74])
    for(const viewStart of [-81,-1,1,17,92]) for(const span of [1,9,37,90]) {
      const options={extent:length,direction,offset,length,viewStart,viewEnd:viewStart+span-1};
      const placements=copies(1,length,options), occupied=new Map(), nativeCounts=new Map();
      const end=Math.min(options.viewEnd,viewStart+length-1);
      for(const copy of placements) for(let p=1;p<=length;p++) {
        const x=base(p,length,direction)+copy-offset;
        if(x<viewStart||x>end) continue;
        assert.ok(!occupied.has(x),'no two bases occupy the same displayed coordinate');
        occupied.set(x,p);nativeCounts.set(p,(nativeCounts.get(p)||0)+1);
      }
      assert.equal(occupied.size,Math.min(span,length));
      assert.ok([...nativeCounts.values()].every(n=>n===1),'no repeated gene/base at both ends');
      for(let x=viewStart;x<=end;x++) assert.ok(occupied.has(x),'no hole in the displayed chromosome');
    }
});

test('linear tracks never wrap and out-of-range blocks remain absent', () => {
  const options={extent:100,direction:-1,offset:0,length:0,viewStart:1,viewEnd:20};
  assert.deepEqual(copies(1,10,options),[]);
  assert.deepEqual(copies(91,100,options),[0]);
});

test('switching blocks and references recomputes direction rather than carrying old reversals', () => {
  const first=[{genome_id:1,strand:'+'},{genome_id:2,strand:'-'},{genome_id:3,strand:'+'}];
  const second=[{genome_id:1,strand:'-'},{genome_id:2,strand:'-'},{genome_id:3,strand:'+'}];
  for(const reference of [1,2,3]) for(const members of [first,second,first,second]) {
    const result=directions(members,reference,true), ref=members.find(m=>m.genome_id===reference);
    assert.equal(result.get(reference),1);
    const displayed=members.map(m=>(m.strand==='+'?1:-1)*result.get(m.genome_id));
    assert.ok(displayed.every(d=>d===(ref.strand==='+'?1:-1)));
    assert.deepEqual([...directions(members,reference,false).values()],[1,1,1]);
  }
});

test('a missing reference uses the first block member, and absent genomes acquire no new direction', () => {
  const members=[{genome_id:2,strand:'-'},{genome_id:3,strand:'+'}];
  assert.deepEqual([...directions(members,1,true)],[[2,1],[3,-1]]);
  assert.equal(directions([],1,true).size,0);
});

const member=(genome_id,start,end,strand='+')=>({genome_id,start,end,strand});
const gene=(genome_id,id,parts)=>({genome_id,id,parts});
const result={genomes:[{id:1},{id:2}],families:[
  {genomes:2,members:[gene(1,'same-id',[{start:1,end:3},{start:98,end:100}]),gene(2,'same-id',[{start:40,end:45}]),gene(2,'copy',[{start:70,end:72}])]},
  {genomes:1,members:[gene(1,'accessory',[{start:20,end:30}])]},
]};
const blocks=[
  {id:1,members:[member(1,1,3),member(2,40,45,'-')]},
  {id:2,members:[member(1,4,39),member(2,46,69)]},
  {id:3,members:[member(1,98,100,'-'),member(2,70,72)]},
  {id:4,members:[member(1,3,3)]},
];

test('core filtering uses actual segments, includes duplicate core copies, and excludes accessory families', () => {
  const index=coreIndex(result,blocks);
  assert.deepEqual([...index.blockIds],[1,3,4]);
  assert.deepEqual([...index.geneKeys],['1:same-id','2:same-id','2:copy']);
  assert.deepEqual([...coreIndex(null,blocks).blockIds],[]);
});

test('core filtering never mutates block strands, positions, or selected-block direction', () => {
  const snapshot=JSON.stringify({result,blocks});
  const index=coreIndex(result,blocks), retained=blocks.filter(b=>index.blockIds.has(b.id));
  for(const reference of [1,2]) for(const block of retained) {
    const original=blocks.find(b=>b.id===block.id);
    assert.deepEqual([...directions(block.members,reference,true)],[...directions(original.members,reference,true)]);
  }
  assert.equal(JSON.stringify({result,blocks}),snapshot);
});
