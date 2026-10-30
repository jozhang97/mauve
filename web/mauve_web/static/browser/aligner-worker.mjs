import createMauve from '../wasm/progressiveMauve.mjs';
import {stageInputs} from './aligner-inputs.mjs';
self.onmessage = async ({data}) => {
  let log = '';
  const flush = () => { if (log) { self.postMessage({type: 'log', text: log}); log = ''; } };
  const print = text => { log += text + '\n'; if (log.length >= 4096) flush(); };
  try {
    const module = await createMauve({noInitialRun: true, print, printErr: print});
    await stageInputs(module, data.inputs);
    const code = module.callMain(data.command);
    flush();
    if (code !== 0) throw Error(`progressiveMauve exited with status ${code}.`);
    const files = {};
    for (const [key, name] of Object.entries({xmfa: 'alignment.xmfa', tree: 'guide.tree', backbone: 'alignment.backbone'})) {
      try { files[key] = new Blob([module.FS.readFile('/' + name)]); } catch (e) { if (key === 'xmfa') throw Error('Aligner did not produce an XMFA alignment.'); }
    }
    self.postMessage({type: 'done', files});
  } catch (error) { flush(); self.postMessage({type: 'error', error: error.message || String(error)}); }
};
