// node [--cpu-prof] web/benchmarks/engine.mjs ENGINE.mjs CASE GENOMES BASES [SEED]
// Use a fresh process for each measurement; compare artifact hashes as well as time.
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {engineCase} from './engine-cases.mjs';
import {stageInputs} from '../mauve_web/static/browser/aligner-inputs.mjs';
import {parseXMFA} from '../mauve_web/static/browser/core.mjs';

const [engine, kind = 'similar', n = '12', length = '100000', seed = '12345'] = process.argv.slice(2);
const genomes = Number(n), bases = Number(length);
// Experimental engine capacity; this does not change the website's input limit.
if (!engine || !Number.isInteger(genomes) || genomes < 2 || genomes > 128 ||
    !Number.isInteger(bases) || bases < 1000 || !Number.isInteger(Number(seed)))
  throw Error('Usage: engine.mjs ENGINE.mjs CASE GENOMES(2–128) BASES(>=1000) [SEED]');
const sequences = engineCase(kind, genomes, bases, Number(seed));
const {default: createMauve} = await import(pathToFileURL(engine).href);
let lastProgress = -Infinity;
const progress = text => {
  if (process.env.MAUVE_BENCHMARK_PROGRESS && performance.now() - lastProgress >= 30000) {
    console.error(new Date().toISOString(), text);
    lastProgress = performance.now();
  }
};
// Capture exported linear memory without changing the generated engine loader.
// Wasm memory cannot shrink, so its final capacity also records its peak capacity.
const instantiate = WebAssembly.instantiate;
let wasmMemory, m;
WebAssembly.instantiate = async (...args) => {
  const result = await instantiate(...args);
  const instance = result.instance || result;
  wasmMemory = Object.values(instance.exports).find(value => value instanceof WebAssembly.Memory);
  return result;
};
try {
  m = await createMauve({noInitialRun: true, print: progress, printErr: progress});
} finally {
  WebAssembly.instantiate = instantiate;
}
await stageInputs(m, sequences.map(s => new Blob(['>genome\n', s, '\n'])));
const start = performance.now();
const exit = m.callMain(['--output=/alignment.xmfa', '--output-guide-tree=/guide.tree',
  '--backbone-output=/alignment.backbone', ...sequences.map((_, i) => `/input-${i + 1}.fa`)]);
const alignment_ms = performance.now() - start;
if (exit !== 0) throw Error('Engine exited with status ' + exit);
const artifacts = {};
for (const name of ['alignment.xmfa', 'guide.tree', 'alignment.backbone']) {
  const bytes = m.FS.readFile('/' + name);
  artifacts[name] = {bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex')};
}
const meta = await parseXMFA(new Blob([m.FS.readFile('/alignment.xmfa')]), () => {});
if (meta.genomes.length !== genomes || !meta.genomes.every((g, i) => g.extent === sequences[i].length))
  throw Error('Alignment does not cover the expected genome extents');
console.log(JSON.stringify({kind, genomes, bases, seed: Number(seed), alignment_ms,
  peak_process_rss_kib: process.resourceUsage().maxRSS,
  wasm_heap_capacity_bytes: wasmMemory?.buffer.byteLength ?? null,
  block_count: meta.block_count, artifacts}));
