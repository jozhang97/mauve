import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {parseXMFA, columnSlice, coordinateColumn, nextDifference, pairCounts, profileMember, indexMember, consumed} from '../mauve_web/static/browser/core.mjs';
import {parseRecords, annotationData, verifyMember, locationParts, normalizeInput} from '../mauve_web/static/browser/genbank.mjs';
const fixture = name => readFile(new URL('../' + name, import.meta.url));
async function parse(text) { const blocks = []; const meta = await parseXMFA(new Blob([text]), b => blocks.push(b)); return {...meta, blocks}; }
test('real yeast fixture, annotations and coordinates', async () => {
  const a = await parse(await fixture('demo.alignment'));
  assert.equal(a.block_count, 5); assert.deepEqual(a.genomes.map(g => g.extent), [693, 2000]);
  const annotations = annotationData(await parseRecords(new Blob([await fixture('demo.gbk')])), true);
  let count = 0; for (const b of a.blocks) for (const m of b.members) if (m.genome_id === 2) count += verifyMember(m, annotations.sequence);
  assert.equal(count, 2000); assert.equal(annotations.records.length, 2);
  assert.ok(annotations.features.some(f => f.name === 'TEL01L-TR'));
  for (const b of a.blocks) for (const m of b.members) {
    const page = columnSlice(m, 0, b.columns);
    for (let c = 0; c < page.positions.length; c++) if (page.positions[c] !== null) assert.equal(coordinateColumn(m, page.positions[c]), c);
  }
});
test('reverse strand, gaps, ambiguity and identity rules', async () => {
  const a = await parse('> 1:10-12 + first.fa\nAC-G\n> 2:21-23 - second.fa\nA-TG\n=\n');
  const [x, y] = a.blocks[0].members;
  assert.deepEqual(columnSlice(x, 0, 4).positions, [10, 11, null, 12]);
  assert.deepEqual(columnSlice(y, 0, 4).positions, [23, null, 22, 21]);
  assert.equal(nextDifference(a.blocks[0]), 1); assert.equal(nextDifference(a.blocks[0], 3), null);
  const p = profileMember(y, 4, 2, pairCounts(y.sequence, x.sequence, 2));
  assert.equal(p.matches, 2); assert.equal(p.gap_columns, 2); assert.equal(p.substitutions, 0);
});
test('sparse rank index across long gaps and exact stride boundary', () => {
  const sequence = 'A' + '-'.repeat(4095) + 'CT'.repeat(1024), m = indexMember({genome_id: 1, start: 1, end: 2049, strand: '-', sequence});
  assert.equal(consumed(m, sequence.length), 2049);
  assert.equal(coordinateColumn(m, 2049), 0); assert.equal(coordinateColumn(m, 2048), 4096);
  assert.equal(coordinateColumn(m, 1), sequence.length - 1);
});
test('malformed XMFA never publishes valid-looking output', async () => {
  for (const text of ['', 'not an alignment', '> 1:1-5 +\nACG\n=', '> 1:1-3 +\nACG\n> 2:1-2 +\nAC\n=', '> 1:0-0 +\nACG\n=', '> 0:1-3 +\nACG\n=', '> 1:1-3 +\nXYZ\n=']) await assert.rejects(parse(text));
});
test('GenBank locations preserve compound strand/fuzzy coordinates and reject unsupported locations', () => {
  assert.deepEqual(locationParts('complement(join(<1..3,8..>10))', 20), [{start:8,end:10,strand:'-',fuzzy:true},{start:1,end:3,strand:'-',fuzzy:true}]);
  for (const s of ['OTHER:1..3', '1^2', '?..4', '3..100']) assert.throws(() => locationParts(s, 10));
});
test('FASTA inputs validate DNA and preserve record offsets', async () => {
  const result = await normalizeInput(new Blob(['>a\n'+'ACGT'.repeat(20)+'\n>b\n'+'A'.repeat(50)]));
  assert.equal(result.bases, 130); assert.deepEqual(result.records.map(r => [r.start,r.end]), [[1,80],[81,130]]);
  await assert.rejects(normalizeInput(new Blob(['>a\n'+'A-'.repeat(50)])));
});
