import test from 'node:test';
import assert from 'node:assert/strict';
import {rankCorrelation, anchoredOrder} from '../mauve_web/static/browser/rank-correlation.mjs';

test('known rank coefficients and undefined short inputs', () => {
  assert.deepEqual(rankCorrelation(['a','b','c'], ['a','b','c']), {n:3,kendall:1,spearman:1});
  assert.deepEqual(rankCorrelation(['a','b','c'], ['c','b','a']), {n:3,kendall:-1,spearman:-1});
  const swap = rankCorrelation(['a','b','c','d'], ['a','c','b','d']);
  assert.ok(Math.abs(swap.kendall - 2/3) < 1e-12);
  assert.equal(swap.spearman, .8);
  assert.deepEqual(rankCorrelation(['a'], ['a']), {n:1,kendall:null,spearman:null});
  assert.throws(() => rankCorrelation(['a','a'], ['a','b']));
  assert.throws(() => rankCorrelation(['a','b'], ['a','c']));
});

test('rotation and whole chromosome reversal are normalized by anchor and orientation', () => {
  const genes = ids => ids.map((family, order) => ({family,order}));
  const a = anchoredOrder(genes(['a','b','c','d']),1,'b');
  const b = anchoredOrder(genes(['c','d','a','b']),1,'b');
  const c = anchoredOrder(genes(['d','c','b','a']),-1,'b');
  assert.deepEqual(a,b); assert.deepEqual(a,c);
  assert.equal(rankCorrelation(a,c).kendall,1);
});

test('Fenwick counts agree with exhaustive pair comparisons for every five-family permutation', () => {
  function* permutations(a) {
    if (!a.length) { yield []; return; }
    for (let i=0;i<a.length;i++) for (const rest of permutations(a.filter((_,j)=>i!==j))) yield [a[i],...rest];
  }
  const a = ['a','b','c','d','e'];
  for (const b of permutations(a)) {
    let d=0;
    for(let i=0;i<5;i++) for(let j=i+1;j<5;j++) if(b.indexOf(a[i])>b.indexOf(a[j])) d++;
    assert.equal(rankCorrelation(a,b).kendall,1-4*d/20);
  }
});
