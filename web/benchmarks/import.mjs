// node --expose-gc web/benchmarks/import.mjs /tmp/mauve-core-baseline.mjs [genomes=12] [bases=1000000] [line-width=80; 0=unwrapped]
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import * as candidate from '../mauve_web/static/browser/core.mjs';

const [baselinePath, genomeArg = '12', baseArg = '1000000', widthArg = '80'] = process.argv.slice(2);
if (!baselinePath) throw Error('Provide the baseline core.mjs path.');
const genomes = Number(genomeArg), bases = Number(baseArg);
const lineWidth = Number(widthArg);
if (![genomes, bases].every(n => Number.isSafeInteger(n) && n > 0)) throw Error('Use positive genome and base counts.');
if (!Number.isSafeInteger(lineWidth) || lineWidth < 0) throw Error('Use a nonnegative line width.');
const baseline = await import(pathToFileURL(resolve(baselinePath)));
const sequence = 'acgtN--'.repeat(Math.ceil(bases / 7)).slice(0, bases);
const residues = sequence.replaceAll('-', '').length;
const wrapped = lineWidth ? Array.from({length: Math.ceil(sequence.length / lineWidth)},
  (_, i) => sequence.slice(i * lineWidth, (i + 1) * lineWidth)).join('\n') : sequence;
const blob = new Blob(Array.from({length: genomes}, (_, i) =>
  `> ${i + 1}:1-${residues} ${i % 2 ? '-' : '+'} genome-${i + 1}.fa\n${wrapped}\n`).concat('=\n'));
const runs = [], hashes = new Set();
for (let repeat = -1; repeat < 5; ++repeat) {
  const order = repeat % 2 ? ['candidate', 'baseline'] : ['baseline', 'candidate'];
  for (const label of order) {
    global.gc?.();
    const blocks = [];
    const start = performance.now();
    const metadata = await ({baseline, candidate}[label]).parseXMFA(blob, b => blocks.push(b));
    const ms = performance.now() - start;
    assert.equal(metadata.genomes.length, genomes);
    assert.equal(blocks.length, 1);
    assert.ok(metadata.genomes.every(g => g.extent === residues));
    const hash = createHash('sha256').update(JSON.stringify(metadata));
    for (const member of blocks[0].members) {
      hash.update(member.sequence);
      hash.update(Buffer.from(member.prefix.buffer, member.prefix.byteOffset, member.prefix.byteLength));
    }
    hashes.add(hash.digest('hex'));
    assert.equal(hashes.size, 1, 'Imported sequences, indexes, and metadata must match.');
    if (repeat >= 0) runs.push({label, repeat, ms});
  }
}
const median = values => values.sort((a, b) => a - b)[Math.floor(values.length / 2)];
const median_ms = Object.fromEntries(['baseline', 'candidate'].map(label =>
  [label, median(runs.filter(r => r.label === label).map(r => r.ms))]));
console.log(JSON.stringify({genomes, columns_per_genome: bases, line_width: lineWidth, input_bytes: blob.size,
  node: process.version, output_sha256: [...hashes][0], median_ms,
  speedup: median_ms.baseline / median_ms.candidate, runs}, null, 2));
