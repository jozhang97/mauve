import test from 'node:test';
import assert from 'node:assert/strict';
import {eligibleGene, adjacencies, circularDCJ, pairMetrics, analyzeGenes} from '../mauve_web/static/browser/gene-analysis.mjs';
import {indexMember} from '../mauve_web/static/browser/core.mjs';
import {parseRecords, annotationData} from '../mauve_web/static/browser/genbank.mjs';

const chr = names => names.map(name => ({family: name.replace('-', ''), strand: name.startsWith('-') ? '-' : '+'}));
const compare = (a, b) => pairMetrics([chr(a)], [chr(b)]);

test('insertion changes content/actual adjacency but not shared order', () => {
  const p = compare(['A', 'X', 'B', 'C'], ['A', 'B', 'C']);
  assert.equal(p.shared, 3); assert.equal(p.union, 4); assert.equal(p.content_jaccard, .75);
  assert.equal(p.adjacency_shared, 2); assert.equal(p.adjacency_union, 5); assert.equal(p.adjacency_jaccard, .4);
  assert.equal(p.order_genes, 3); assert.equal(p.conservation, 1); assert.equal(p.dcj, 0);
});
test('rotation, whole chromosome reverse complement, inversion and orientation', () => {
  const a = ['A', 'B', 'C', 'D'];
  for (const b of [['C', 'D', 'A', 'B'], ['-D', '-C', '-B', '-A']]) {
    const p = compare(a, b); assert.equal(p.adjacency_jaccard, 1); assert.equal(p.conservation, 1); assert.equal(p.dcj, 0);
  }
  const p = compare(a, ['A', '-C', '-B', 'D']);
  assert.equal(p.dcj, 1); assert.equal(p.conservation, .5);
  assert.equal(compare(a, ['A', '-B', 'C', 'D']).dcj, 1);
});
test('separate circular chromosomes, fusion, duplicate exclusion and empty sets', () => {
  const p = pairMetrics([chr(['A', 'B']), chr(['C', 'D'])], [chr(['A', 'B', 'C', 'D'])]);
  assert.equal(p.dcj, 1); assert.equal(p.conservation, .5);
  const d = compare(['A', 'A', 'B', 'C'], ['A', 'B', 'C']);
  assert.equal(d.shared, 3); assert.equal(d.genes_a, 4); assert.equal(d.families_a, 3);
  assert.equal(d.excluded_shared, 1); assert.equal(d.order_genes, 2); assert.equal(d.dcj, 0);
  const empty = compare([], []); assert.equal(empty.content_jaccard, null); assert.equal(empty.dcj, null); assert.equal(empty.conservation, null);
  const disjoint = compare(['A'], ['B']); assert.equal(disjoint.content_jaccard, 0); assert.equal(disjoint.dcj, null);
  assert.equal(compare(['A'], ['-A']).dcj, 0);
});
test('DCJ formula agrees with exhaustive shortest paths over all 105 four-gene adjacency matchings', () => {
  const key = (a, b) => JSON.stringify(a < b ? [a, b] : [b, a]);
  const encode = edges => [...edges].sort().join('|');
  const initial = adjacencies([chr(['A', 'B', 'C', 'D'])]);
  const queue = [[initial, 0]], visited = new Set([encode(initial)]);
  for (let q = 0; q < queue.length; q++) {
    const [edges, distance] = queue[q];
    assert.equal(circularDCJ(initial, edges, 4), distance);
    const entries = [...edges];
    for (let i = 0; i < entries.length; i++) for (let j = i + 1; j < entries.length; j++) {
      const [a, b] = JSON.parse(entries[i]), [c, d] = JSON.parse(entries[j]);
      for (const replacements of [[key(a, c), key(b, d)], [key(a, d), key(b, c)]]) {
        const next = new Set(edges); next.delete(entries[i]); next.delete(entries[j]); replacements.forEach(x => next.add(x));
        const id = encode(next); if (!visited.has(id)) { visited.add(id); queue.push([next, distance + 1]); }
      }
    }
  }
  assert.equal(visited.size, 105);
});

function fixture() {
  const sequences = ['A'.repeat(40), 'A'.repeat(10) + '-'.repeat(10) + 'A'.repeat(20), 'A'.repeat(10) + 'T'.repeat(10) + 'A'.repeat(20)];
  const genomes = sequences.map((_, i) => ({id: i + 1, name: `Genome ${i + 1}`}));
  const members = sequences.map((sequence, i) => indexMember({genome_id: i + 1, start: 1, end: sequence.replaceAll('-', '').length, strand: '+', sequence}));
  const sources = members.map((m, i) => ({genome_id: i + 1, metadata: {analysis_version: 1, records: [{name: 'chr', start: 1, end: m.end, topology: 'circular'}]},
    features: Array.from({length: m.end / 10}, (_, j) => ({id: `${i + 1}:${j}`, name: `g${j}`, locus_tag: `l${j}`, type: 'CDS', record: 'chr', start: 10 * j + 1, end: 10 * j + 10, strand: '+', parts: [{start: 10 * j + 1, end: 10 * j + 10, strand: '+', fuzzy: false}]}))}));
  return {input: {genomes, sources, blocks: [{id: 1, members}]}, load: async (_, gid) => members.find(m => m.genome_id === gid)};
}
test('alignment-derived families give all pairs and core/pan occupancy, not name matches', async () => {
  const {input, load} = fixture();
  const r = await analyzeGenes(input, load);
  assert.equal(r.pairs.length, 3); assert.equal(r.pan, 5); assert.equal(r.core, 3); assert.equal(r.single_copy_core, 3);
  assert.equal(r.genome_specific, 2); assert.equal(r.accessory, 2); assert.deepEqual(r.occupancy, [2, 0, 3]);
  const p = r.pairs[0]; assert.equal(p.shared, 3); assert.equal(p.union, 4); assert.equal(p.adjacency_jaccard, .4); assert.equal(p.dcj, 0);
  assert.equal(r.families.reduce((n, f) => n + f.members.length, 0), 11);
});
test('identity thresholds, gaps, ambiguity and type affect matches', async () => {
  const {input, load} = fixture();
  input.sources[2].features[0].type = 'tRNA';
  input.blocks[0].members[2].sequence.fill(78, 20, 30);
  const r = await analyzeGenes(input, load);
  assert.equal(r.core, 1); assert.equal(r.pan, 7);
  const strict = await analyzeGenes(input, load, {rna: 'experimental'});
  assert.equal(strict.genomes[2].genes, 3);
  await assert.rejects(analyzeGenes(input, load, {coverage: 0}), /Coverage/);
});
test('multi-part genes and coverage aggregate across alignment blocks', async () => {
  const {input} = fixture(); input.genomes = input.genomes.slice(0, 2); input.sources = input.sources.slice(0, 2);
  for (const source of input.sources) source.features = [{...source.features[0], start: 1, end: 10, parts: [{start: 1, end: 4}, {start: 7, end: 10}]}];
  input.blocks = [1, 7].map((start, i) => ({id: i, members: [1, 2].map(genome_id => indexMember({genome_id, start, end: start + 3, strand: '+', sequence: 'AAAA'}))}));
  const r = await analyzeGenes(input, async (bid, gid) => input.blocks[bid].members.find(m => m.genome_id === gid));
  assert.equal(r.pan, 1); assert.equal(r.core, 1); assert.equal(r.pairs[0].dcj, 0);
});
test('reverse-oriented alignments infer the same genes with reversed genomic order', async () => {
  const {input} = fixture(); input.genomes = input.genomes.slice(0, 2); input.sources = [input.sources[0], structuredClone(input.sources[0])];
  input.sources[1].genome_id = 2; input.sources[1].features.forEach(f => { f.strand = '-'; f.parts[0].strand = '-'; });
  const a = input.blocks[0].members[0], b = indexMember({...a, genome_id: 2, strand: '-'});
  input.blocks = [{id: 1, members: [a, b]}];
  const r = await analyzeGenes(input, async (_, gid) => gid === 1 ? a : b);
  assert.equal(r.core, 4); assert.equal(r.pairs[0].adjacency_jaccard, 1); assert.equal(r.pairs[0].dcj, 0);
});
test('missing, legacy, linear and overlapping data fail explicitly', async () => {
  for (const [mutate, pattern] of [
    [x => x.genomes.splice(1), /at least two/],
    [x => x.sources.pop(), /Import GenBank/],
    [x => delete x.sources[0].metadata.analysis_version, /Reimport/],
    [x => x.sources[0].metadata.records[0].topology = 'linear', /linear/],
    [x => x.blocks.push({...x.blocks[0], id: 2}), /overlapping/],
  ]) { const {input, load} = fixture(); mutate(input); await assert.rejects(analyzeGenes(input, load), pattern); }
});
test('RNA evidence, pseudo flags, unknown strands and fuzzy coordinates', () => {
  const f = fixture().input.sources[0].features[0];
  assert.equal(eligibleGene(f), true); assert.equal(eligibleGene({...f, type: 'gene'}), false);
  assert.equal(eligibleGene({...f, pseudo: true}), false); assert.equal(eligibleGene({...f, strand: '.'}), false);
  assert.equal(eligibleGene({...f, parts: [{start: 1, end: 10, fuzzy: true}]}), false);
  assert.equal(eligibleGene({...f, type: 'rRNA'}), true); assert.equal(eligibleGene({...f, type: 'rRNA'}, 'experimental'), false);
  assert.equal(eligibleGene({...f, type: 'ncRNA', inference: 'profile match'}), false);
  assert.equal(eligibleGene({...f, type: 'ncRNA', experiment: 'Northern blot'}), true);
});
test('GenBank import retains circular topology, evidence and pseudogene flags', async () => {
  const data = await parseRecords(new Blob([`LOCUS       chr 30 bp DNA circular
FEATURES             Location/Qualifiers
     CDS             1..10
                     /pseudo
     ncRNA           11..20
                     /experiment="Northern blot"
                     /inference="profile match"
     tRNA            21..30
ORIGIN
        1 aaaaaaaaaa aaaaaaaaaa aaaaaaaaaa
//
`]));
  const annotation = annotationData(data, false);
  assert.equal(annotation.records[0].topology, 'circular'); assert.equal(annotation.features[0].pseudo, true);
  assert.equal(annotation.features[1].experiment, 'Northern blot'); assert.equal(annotation.features[1].inference, 'profile match');
});

test('genes crossing the circular origin match across blocks and preserve cyclic order', async () => {
  const {input} = fixture(); input.genomes = input.genomes.slice(0, 2); input.sources = input.sources.slice(0, 2);
  const make = (start, end, parts = [{start, end}]) => ({type: 'CDS', name: 'gene', record: 'chr', strand: '+', start, end, parts});
  input.sources[0].features = [make(1, 40, [{start: 31, end: 40}, {start: 1, end: 10}]), make(11, 20), make(21, 30)];
  input.sources[1].metadata.records[0].end = 40;
  input.sources[1].features = [make(1, 20), make(21, 30), make(31, 40)];
  input.blocks = [[1, 10, 11, 20], [11, 30, 21, 40], [31, 40, 1, 10]].map(([as, ae, bs, be], i) => ({id: i, members: [
    indexMember({genome_id: 1, start: as, end: ae, strand: '+', sequence: 'A'.repeat(ae - as + 1)}),
    indexMember({genome_id: 2, start: bs, end: be, strand: '+', sequence: 'A'.repeat(be - bs + 1)}),
  ]}));
  const r = await analyzeGenes(input, async (bid, gid) => input.blocks[bid].members.find(m => m.genome_id === gid));
  assert.equal(r.core, 3); assert.equal(r.pan, 3); assert.equal(r.pairs[0].adjacency_jaccard, 1); assert.equal(r.pairs[0].dcj, 0);
});
test('transitive matches retain duplicated families for content and exclude them from order', async () => {
  const {input, load} = fixture();
  input.sources[0].features.push({...input.sources[0].features[0], id: 'copy', locus_tag: 'copy'});
  const r = await analyzeGenes(input, load);
  assert.equal(r.core, 3); assert.equal(r.pan, 5); assert.equal(r.duplicated_families, 1); assert.equal(r.single_copy_core, 2);
  assert.equal(r.pairs[0].excluded_shared, 1); assert.equal(r.pairs[0].order_genes, 2); assert.equal(r.pairs[0].dcj, 0);
});
