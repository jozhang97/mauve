import {alignerConfig} from './aligner-config.mjs';
import {stageInputs} from './aligner-inputs.mjs';
self.onmessage = async ({data}) => {
  const started = performance.now();
  let log = '';
  const flush = () => { if (log) { self.postMessage({type: 'log', text: log}); log = ''; } };
  const print = text => { log += text + '\n'; if (log.length >= 4096) flush(); };
  try {
    const config = alignerConfig(globalThis, data.threads);
    const {default: createMauve} = await import(`../${config.directory}/progressiveMauve.mjs`);
    let complete, fail;
    const exited = new Promise((resolve, reject) => { complete = resolve; fail = reject; });
    // A rejected initialization must not leave an unhandled exit promise.
    exited.catch(() => {});
    const module = await createMauve({noInitialRun: true, print, printErr: print,
      mauveThreads: config.threads, onExit: complete, onAbort: message => fail(Error(String(message))),
      preRun: [module => { module.ENV.MAUVE_THREADS = String(config.threads); }]});
    print(`Mauve browser: up to ${config.threads} alignment thread(s)`);
    await stageInputs(module, data.inputs);
    const alignmentStarted = performance.now();
    const result = module.callMain(data.command);
    const code = config.threaded ? await exited : result;
    const alignmentMs = performance.now() - alignmentStarted;
    flush();
    if (code !== 0) throw Error(`progressiveMauve exited with status ${code}.`);
    const files = {};
    for (const [key, name] of Object.entries({xmfa: 'alignment.xmfa', tree: 'guide.tree', backbone: 'alignment.backbone'})) {
      try { files[key] = new Blob([module.FS.readFile('/' + name)]); } catch (e) { if (key === 'xmfa') throw Error('Aligner did not produce an XMFA alignment.'); }
    }
    self.postMessage({type: 'done', files, metrics: {threads: config.threads,
      alignmentMs, totalMs: performance.now() - started}});
  } catch (error) { flush(); self.postMessage({type: 'error', error: error.message || String(error)}); }
};
