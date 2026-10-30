// node --expose-gc verify-annotations.mjs BASELINE_GENBANK.mjs OUTPUT.json
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
import {readFile, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
const [baselinePath, output, candidatePath] = process.argv.slice(2);
const candidateURL = candidatePath ? pathToFileURL(resolve(candidatePath)) : new URL('../mauve_web/static/browser/genbank.mjs', import.meta.url);
const {verifyMember: candidate} = await import(candidateURL);
if (!output) throw Error('Provide baseline genbank.mjs and output JSON');
const {verifyMember: baseline} = await import(pathToFileURL(resolve(baselinePath)));
const sources = {baseline: baselinePath, candidate: candidateURL};
const source_sha256 = Object.fromEntries(await Promise.all(Object.entries(sources).map(async ([k, path]) => [k, createHash('sha256').update(await readFile(path)).digest('hex')])));
const report = {node: process.version, source_sha256, cases: []};
const complement = {65: 84, 84: 65, 67: 71, 71: 67};
for (const kind of ['forward', 'reverse', 'reverse-mixed-gaps']) {
  const pattern = kind.endsWith('gaps') ? 'ACGTNRYSWKMBDHV' : 'ACGT';
  const genome = new TextEncoder().encode(pattern.repeat(Math.ceil(1000000 / pattern.length)).slice(0, 1000000));
  const bases = kind === 'forward' ? genome : genome.slice().reverse().map(x => complement[x] || x);
  let sequence = bases;
  if (kind.endsWith('gaps')) {
    sequence = new Uint8Array(bases.length + Math.floor(bases.length / 31));
    let offset = 0;
    for (let i = 0; i < bases.length; i++) {sequence[offset++] = bases[i]; if (i % 31 === 30) sequence[offset++] = 45;}
  }
  const member = {start: 1, end: genome.length, strand: kind === 'forward' ? '+' : '-', sequence};
  const expected = genome.reduce((n, x) => n + Number([65, 67, 71, 84].includes(x)), 0);
  for (const fn of [baseline, candidate]) assert.equal(fn(member, genome), expected);
  const runs = {baseline: [], candidate: []};
  for (let repeat = 0; repeat < 5; repeat++) for (const label of repeat % 2 ? ['candidate', 'baseline'] : ['baseline', 'candidate']) {
    global.gc?.();
    const start = performance.now();
    const count = ({baseline, candidate}[label])(member, genome);
    runs[label].push(performance.now() - start);
    assert.equal(count, expected);
  }
  const median = values => [...values].sort((a, b) => a - b)[2];
  const medians_ms = Object.fromEntries(Object.entries(runs).map(([k, v]) => [k, median(v)]));
  report.cases.push({kind, genome_bases: genome.length, alignment_columns: sequence.length, verified_bases: expected, medians_ms, runs_ms: runs, speedup: medians_ms.baseline / medians_ms.candidate});
  console.log(JSON.stringify(report.cases.at(-1)));
}
await writeFile(output, JSON.stringify(report, null, 2) + '\n');
