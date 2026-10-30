// Compare native ARM64 results against the shipped Wasm engine. File paths are
// the only normalized output fields; all alignment/scoring bytes must agree.
import {mkdtemp, writeFile, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
import createMauve from '../mauve_web/static/wasm/progressiveMauve.mjs';
import {stageInputs} from '../mauve_web/static/browser/aligner-inputs.mjs';
import {engineCase} from './engine-cases.mjs';
import {parseXMFA} from '../mauve_web/static/browser/core.mjs';
import assert from 'node:assert/strict';

const executable = resolve(process.argv[2]);
const option = name => { const i = process.argv.indexOf(name); return i < 0 ? null : process.argv[i+1]; };
const genomesOverride = option('--genomes') === null ? null : Number(option('--genomes'));
if (genomesOverride !== null && (!Number.isInteger(genomesOverride) || genomesOverride < 2 || genomesOverride > 128)) throw Error('--genomes must be 2–128');
const basesOverride = option('--bases') === null ? null : Number(option('--bases'));
if (basesOverride !== null && (!Number.isInteger(basesOverride) || basesOverride < 1000)) throw Error('--bases must be at least 1000');
const measurements = [];
const work = await mkdtemp(join(tmpdir(), 'mauve-native-parity-'));
const normalize = text => text.replace(/^(#Sequence\d+File\s+)\/?(input-\d+\.fa)$/gm, '$1/$2')
  .replace(/^(> \d+:\d+-\d+ [+-]\s+)\/?(input-\d+\.fa)$/gm, '$1/$2');
try {
  const cases = genomesOverride === null ? [['similar',12,100000],['divergent',4,20000],['rearranged',4,50000],['repeats',4,50000],['ambiguous',4,20000]] : [['similar',genomesOverride,100000]];
  for (const [kind, genomes, bases] of cases) {
    const sequences = engineCase(kind, process.argv.includes('--full') || genomesOverride !== null ? genomes : 4, basesOverride ?? (process.argv.includes('--full') || genomesOverride !== null ? bases : 5000), 12345);
    const names = sequences.map((_, i) => `input-${i+1}.fa`);
    for (let i = 0; i < names.length; i++) await writeFile(join(work, names[i]), `>genome\n${sequences[i]}\n`);
    const flags = ['--output=alignment.xmfa', '--output-guide-tree=guide.tree', '--backbone-output=alignment.backbone'];
    const nativeStart = performance.now();
    const native = spawnSync(executable, [...flags, ...names], {cwd: work, env: {...process.env, MAUVE_THREADS: '8'}, timeout: 60000, encoding: 'utf8', maxBuffer: 16*1024*1024});
    const nativeWallMs = performance.now() - nativeStart;
    assert.equal(native.status, 0, `${native.error || native.signal || ''} ${native.stderr}`);
    const module = await createMauve({noInitialRun: true, print: () => {}, printErr: () => {}});
    await stageInputs(module, sequences.map(s => new Blob([`>genome\n${s}\n`])));
    const wasmStart = performance.now();
    assert.equal(module.callMain([...flags, ...names.map(n => '/'+n)]), 0);
    const wasmAlignmentMs = performance.now() - wasmStart;
    for (const name of ['alignment.xmfa', 'guide.tree', 'alignment.backbone']) {
      const actual = normalize(await readFile(join(work, name), 'utf8'));
      const expected = normalize(new TextDecoder().decode(module.FS.readFile(name)));
      assert.equal(actual, expected, `${kind}: ${name}`);
      if (name === 'alignment.xmfa') {
        const meta = await parseXMFA(new Blob([actual]), () => {});
        assert.deepEqual(meta.genomes.map(g => g.extent), sequences.map(s => s.length));
      }
    }
    measurements.push({kind, genomes:sequences.length, bases:sequences[0].length, native_threads:8, native_process_ms:nativeWallMs, wasm_alignment_ms:wasmAlignmentMs, outputs_identical:true});
    console.log(`${kind}: native 8-thread and Wasm artifacts match (file paths normalized)`);
    // Native cached indexes must not survive when the fixture sequences change.
    const {readdir} = await import('node:fs/promises');
    for (const file of await readdir(work)) await rm(join(work, file), {recursive:true, force:true});
  }
  if (option('--output')) await writeFile(option('--output'), JSON.stringify({measurements, note:'Single native-then-Wasm parity run per case. Native timing includes process startup; Wasm timing excludes initialization. Normalize only XMFA input-file path fields.'}, null, 2)+'\n');
} finally {
  await rm(work, {recursive: true, force: true});
}
