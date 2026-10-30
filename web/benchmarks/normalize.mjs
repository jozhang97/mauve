// Save baseline genbank.mjs and core.mjs together, then:
// node --expose-gc web/benchmarks/normalize.mjs /tmp/baseline/genbank.mjs [bases-per-record=1000000]
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {normalizeInput as candidate} from '../mauve_web/static/browser/genbank.mjs';

const [baselinePath, countArg = '1000000'] = process.argv.slice(2);
const count = Number(countArg);
if (!baselinePath || !Number.isSafeInteger(count) || count < 50) throw Error('Provide a baseline module and at least 50 bases.');
const {normalizeInput: baseline} = await import(pathToFileURL(resolve(baselinePath)));
const sequence = 'acgtn'.repeat(Math.ceil(count / 5)).slice(0, count).match(/.{1,80}/g).join('\n');
const input = new Blob(['>one\n', sequence, '\n>two\n', sequence, '\n']);
const runs = [], hashes = new Set();
for (let repeat = -1; repeat < 5; ++repeat) {
  for (const label of repeat % 2 ? ['candidate', 'baseline'] : ['baseline', 'candidate']) {
    global.gc?.();
    const start = performance.now();
    const result = await ({baseline, candidate}[label])(input);
    const ms = performance.now() - start;
    assert.equal(result.bases, count * 2);
    assert.equal(result.records.length, 2);
    hashes.add(createHash('sha256').update(new Uint8Array(await result.normalized.arrayBuffer()))
      .update(JSON.stringify({records: result.records, bases: result.bases, format: result.format})).digest('hex'));
    assert.equal(hashes.size, 1, 'Normalized FASTA and record metadata must match.');
    if (repeat >= 0) runs.push({label, repeat, ms});
  }
}
const median_ms = Object.fromEntries(['baseline', 'candidate'].map(label =>
  [label, runs.filter(r => r.label === label).map(r => r.ms).sort((a, b) => a - b)[2]]));
console.log(JSON.stringify({records: 2, bases_per_record: count, node: process.version,
  median_ms, speedup: median_ms.baseline / median_ms.candidate, output_sha256: [...hashes][0], runs}, null, 2));
