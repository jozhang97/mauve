import {test} from 'node:test';
import assert from 'node:assert/strict';
import '../mauve_web/static/replication.js';
const {model,classify} = globalThis.mauveReplication;
test('native replichores rotate across coordinate origin and classify whole genes', () => {
  const m=model({start:1,end:100,topology:'circular',replication_origin:76});
  assert.equal(m.terminus,26);
  assert.equal(classify(m,[{start:80,end:90,strand:'+'}]),'co-oriented');
  assert.equal(classify(m,[{start:5,end:10,strand:'+'}]),'co-oriented');
  assert.equal(classify(m,[{start:30,end:40,strand:'+'}]),'head-on');
  assert.equal(classify(m,[{start:30,end:40,strand:'-'}]),'co-oriented');
  assert.equal(classify(m,[{start:20,end:30,strand:'+'}]),'boundary');
  assert.equal(classify(m,[{start:20,end:22,strand:'.'}]),'unknown');
});
test('normalization establishes origin but unsupported replication stays unknown', () => {
  const r={start:1,end:100,topology:'circular'};
  assert.equal(model(r),null);
  assert.equal(model(r,{status:'rotated'}).origin,1);
  assert.equal(model({...r,topology:'linear'},{status:'rotated'}),null);
  assert.equal(model({...r,replication_direction:'RIGHT'},{status:'rotated'}),null);
});
