import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {hashCodingSequences, annotateEssentiality} from '../mauve_web/static/browser/essentiality.mjs';
import {annotationData, parseRecords} from '../mauve_web/static/browser/genbank.mjs';
const fixture = JSON.parse(readFileSync(new URL('../data/essentiality/test-cds.json', import.meta.url)));
const snapshot = JSON.parse(readFileSync(new URL('../mauve_web/static/essentiality-ecoli.json', import.meta.url)));
const reverse = s => [...s].reverse().map(c => ({A:'T', T:'A', G:'C', C:'G'})[c]).join('');

test('hashes forward, reverse, compound and origin-rotated CDS identically', async () => {
  for (const strand of ['+', '-']) for (const rotation of [0, 17]) {
    const original = fixture[0].sequence, sequence = strand === '+' ? original : reverse(original);
    const mid = 30;
    const loc = `join(1..${mid},${mid+1}..${sequence.length})`;
    const gb = `LOCUS       chr ${sequence.length} bp DNA circular\nVERSION     chr\nFEATURES             Location/Qualifiers\n     CDS             ${strand === '+' ? loc : `complement(${loc})`}\nORIGIN\n        1 ${sequence}\n//\n`;
    const parsed = annotationData(await parseRecords(new Blob([gb])), false, rotation);
    await hashCodingSequences(parsed);
    assert.equal(parsed.features[0].sequence_sha256, fixture[0].sha256);
  }
});

test('reference calls require full sequence hashes, preserve ambiguity, and do not transfer to family members', () => {
  const members = fixture.map(f => ({sequence_sha256:f.sha256}));
  members.push({name: 'rplL', record:'CP009273.1'});
  const result = {families:[{members}]};
  annotateEssentiality(result, snapshot);
  assert.equal(members[0].essentiality.status, 'essential');
  assert.equal(members[1].essentiality.status, 'nonessential');
  assert.equal(members[2].essentiality.status, 'unknown');
  assert.equal(result.families[0].essentiality.status, 'essential / nonessential');
  assert.match(members[0].essentiality.basis, /strain essentiality not established/);
  const unclear = Object.entries(snapshot.sequences).find(([, v]) => v.some(m => m.status === 'unclear'))[0];
  const other = {families:[{members:[{sequence_sha256:unclear}]}]};
  annotateEssentiality(other, snapshot);
  assert.equal(other.families[0].essentiality.status, 'unclear');
});

test('fuzzy, pseudo and ambiguous nucleotide CDS get no sequence evidence', async () => {
  const parsed = {sequence:new TextEncoder().encode('ACNT'), features:[
    {type:'CDS', strand:'+', parts:[{start:1,end:4}]},
    {type:'CDS', strand:'+', parts:[{start:1,end:2,fuzzy:true}]},
    {type:'CDS', strand:'+', pseudo:true, parts:[{start:1,end:2}]}]};
  await hashCodingSequences(parsed);
  assert.ok(parsed.features.every(f => !f.sequence_sha256));
});


test('invalid snapshots fail before attaching partial evidence or provenance', () => {
  const result = {families:[{members:[{sequence_sha256:fixture[0].sha256}]}]};
  const original = JSON.stringify(result);
  const invalid = structuredClone(snapshot);
  invalid.sequences[fixture[1].sha256][0].status = 'invalid';
  assert.throws(() => annotateEssentiality(result, invalid), /Invalid essentiality/);
  assert.equal(JSON.stringify(result), original);
});
