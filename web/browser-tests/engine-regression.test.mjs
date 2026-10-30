import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import createMauve from '../mauve_web/static/wasm/progressiveMauve.mjs';
import {engineCase} from '../benchmarks/engine-cases.mjs';
import {stageInputs} from '../mauve_web/static/browser/aligner-inputs.mjs';

const baseline = JSON.parse(await readFile(new URL('./fixtures/engine-baseline.json', import.meta.url)));
for (const fixture of baseline.cases) {
  test(`optimized engine preserves baseline artifacts: ${fixture.kind}`, async () => {
    const m = await createMauve({noInitialRun: true, print: () => {}, printErr: () => {}});
    const sequences = engineCase(fixture.kind, fixture.genomes, fixture.bases, fixture.seed);
    await stageInputs(m, sequences.map(s => new Blob(['>genome\n', s, '\n'])));
    assert.equal(m.callMain(['--output=/alignment.xmfa', '--output-guide-tree=/guide.tree',
      '--backbone-output=/alignment.backbone', ...sequences.map((_, i) => `/input-${i + 1}.fa`)]), 0);
    for (const [name, expected] of Object.entries(fixture.artifacts)) {
      const bytes = m.FS.readFile('/' + name);
      assert.equal(bytes.length, expected.bytes, name);
      assert.equal(createHash('sha256').update(bytes).digest('hex'), expected.sha256, name);
    }
  });
}
