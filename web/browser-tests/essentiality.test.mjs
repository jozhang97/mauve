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


test('legacy CDS annotations report unavailable instead of zero essential matches', () => {
  const result = {families:[{members:[{type:'CDS', name:'rplL'}]}]};
  assert.throws(() => annotateEssentiality(result, snapshot), /checksums are missing/);
  assert.equal(result.essentiality_source, undefined);
  assert.equal(result.families[0].essentiality, undefined);
});

const hpSnapshot = JSON.parse(readFileSync(new URL('../mauve_web/static/essentiality-hpylori.json', import.meta.url)));
test('H. pylori selects its own assay using CDS evidence and leaves variants unknown', async () => {
  const {annotateEssentialityReferences} = await import('../mauve_web/static/browser/essentiality.mjs');
  const [hash] = Object.entries(hpSnapshot.sequences).find(([,v]) => v.some(e=>e.status==='essential'));
  const result = {families:[{members:[{type:'CDS',sequence_sha256:hash}, {type:'CDS',sequence_sha256:'f'.repeat(64)}]}]};
  annotateEssentialityReferences(result, [snapshot,hpSnapshot]);
  assert.equal(result.essentiality_source.id,'chalker-2001-hpylori');
  assert.equal(result.essentiality_matched_copies,1);
  assert.equal(result.families[0].members[0].essentiality.status,'essential');
  assert.equal(result.families[0].members[1].essentiality.status,'unknown');
  assert.match(result.essentiality_reference_note,/untested genes remain unknown/);
  const other = {families:[{members:[{type:'CDS',sequence_sha256:fixture[0].sha256}]}]};
  annotateEssentialityReferences(other, [snapshot,hpSnapshot]);
  assert.equal(other.essentiality_source.id,'goodall-2018-galaxy');
});

const bsSnapshot = JSON.parse(readFileSync(new URL('../mauve_web/static/essentiality-bsubtilis.json', import.meta.url)));
test('B. subtilis selects the Koo assay and never infers calls from gene names or family membership', async () => {
  const {annotateEssentialityReferences} = await import('../mauve_web/static/browser/essentiality.mjs');
  const hash = Object.keys(bsSnapshot.sequences)[0];
  const result = {families:[{members:[{type:'CDS',sequence_sha256:hash}, {type:'CDS',name:'dnaA',sequence_sha256:'f'.repeat(64)}]}]};
  annotateEssentialityReferences(result, [snapshot,hpSnapshot,bsSnapshot]);
  assert.equal(result.essentiality_source.id,'koo-2017-bsubtilis');
  assert.equal(result.essentiality_matched_copies,1);
  assert.equal(result.families[0].members[0].essentiality.status,'essential');
  assert.equal(result.families[0].members[1].essentiality.status,'unknown');
  assert.match(result.essentiality_source.conditions,/LB at 37 C/);
});
