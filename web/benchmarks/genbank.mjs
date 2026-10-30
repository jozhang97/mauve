// Usage: node --expose-gc genbank.mjs BASELINE_DIR CANDIDATE_DIR OUTPUT.json
import {readFile, writeFile} from 'node:fs/promises';
import {resolve, join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
const [baseline, candidate, output] = process.argv.slice(2);
if (!output) throw Error('Provide baseline/candidate module directories and output path');
const sources = {baseline: resolve(baseline), candidate: resolve(candidate)};
const engines = {};
const source_sha256 = {};
for (const [name, directory] of Object.entries(sources)) {
  engines[name] = (await import(pathToFileURL(join(directory, 'genbank.mjs')))).parseRecords;
  source_sha256[name] = {};
  for (const file of ['core.mjs', 'genbank.mjs']) source_sha256[name][file] = createHash('sha256').update(await readFile(join(directory, file))).digest('hex');
}
const bases = 5000000, sequence = 'acgtn'.repeat(bases / 5);
const features = Array.from({length: 10000}, (_, i) => `     gene            ${i * 100 + 1}..${i * 100 + 50}\n                     /gene="gene-${i}"\n                     /note="test β annotation"`).join('\n');
const report = {node: process.version, bases, features: 10000, source_sha256, cases: []};
for (const width of [60, 0]) {
  const origin = width ? Array.from({length: Math.ceil(bases / width)}, (_, i) => String(i * width + 1).padStart(9) + ' ' + sequence.slice(i * width, (i + 1) * width)).join('\n') : '        1 ' + sequence;
  const blob = new Blob([`LOCUS       synthetic ${bases} bp\nFEATURES             Location/Qualifiers\n${features}\nORIGIN\n${origin}\n//\n`]);
  let expected;
  const runs = {baseline: [], candidate: []};
  for (const fn of Object.values(engines)) await fn(blob);
  for (let repeat = 0; repeat < 5; repeat++) for (const label of repeat % 2 ? ['candidate', 'baseline'] : ['baseline', 'candidate']) {
    global.gc?.();
    const start = performance.now();
    const records = await engines[label](blob);
    runs[label].push(performance.now() - start);
    assert.equal(records.length, 1); assert.equal(records[0].sequence.length, bases); assert.equal(records[0].features.length, 10000);
    const hash = createHash('sha256');
    for (const {sequence, ...metadata} of records) hash.update(JSON.stringify(metadata)).update(sequence);
    const signature = hash.digest('hex');
    expected ??= signature;
    assert.equal(signature, expected);
  }
  const median = values => [...values].sort((a, b) => a - b)[2];
  const medians_ms = Object.fromEntries(Object.entries(runs).map(([k, v]) => [k, median(v)]));
  report.cases.push({width, input_bytes: blob.size, runs_ms: runs, medians_ms, speedup: medians_ms.baseline / medians_ms.candidate, output_sha256: expected});
  console.log(JSON.stringify(report.cases.at(-1)));
}
await writeFile(output, JSON.stringify(report, null, 2) + '\n');
