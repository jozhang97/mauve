"""Real Chromium worker timing and exact artifact parity, with bounded run time.

Example: web/.venv/bin/python web/benchmarks/browser-thread-scaling.py --output /tmp/browser.json
Use --genomes 32 --bases 100000 --repeats 3 for the larger scaling workload.
"""
import argparse
import functools
import hashlib
import http.server
import json
from pathlib import Path
import platform
import subprocess
import threading
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def translate_path(self, path):
            relative = path.split('?', 1)[0].removeprefix('/mauve_web/static/wasm-threaded/')
            if args.threaded_assets and relative != path and relative in ('progressiveMauve.mjs', 'progressiveMauve.wasm'):
                return str(args.threaded_assets / relative)
            return super().translate_path(path)
        def end_headers(self):
            self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
            self.send_header('Cross-Origin-Embedder-Policy', 'credentialless')
            super().end_headers()
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            page = browser.new_page()
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            assert page.evaluate('crossOriginIsolated')
            info = {'engine_sha256': {name: hashlib.sha256(((args.threaded_assets if name == 'wasm-threaded' and args.threaded_assets else ROOT / 'mauve_web/static' / name) / 'progressiveMauve.wasm').read_bytes()).hexdigest() for name in ['wasm', 'wasm-threaded']}, 'browser': browser.version, 'platform': platform.platform(), 'hardware_concurrency': page.evaluate('navigator.hardwareConcurrency')}
            cases = ['similar'] if args.genomes else ['similar', 'divergent', 'rearranged', 'repeats', 'ambiguous', 'unrelated-first']
            for kind in cases:
                expected = None
                for repeat in range(args.repeats):
                    for threads in (args.threads if repeat % 2 == 0 else args.threads[::-1]):
                        power_before = subprocess.check_output(['pmset', '-g', 'batt'], text=True).strip() if platform.system() == 'Darwin' else None
                        value = page.evaluate('''async ({kind, genomes, bases, threads, seedFamily, collinear}) => {
                          const {engineCase} = await import('/benchmarks/engine-cases.mjs');
                          const sequences = kind === 'unrelated-first'
                            ? [...engineCase('similar', 1, bases, 98765), ...engineCase('similar', genomes - 1, bases, 12345)]
                            : engineCase(kind, genomes, bases, 12345);
                          const inputs = sequences.map(s => new Blob([`>genome\\n${s}\\n`]));
                          const command = ['--output=/alignment.xmfa', '--output-guide-tree=/guide.tree', '--backbone-output=/alignment.backbone', ...inputs.map((_,i) => `/input-${i+1}.fa`)];
                          if (seedFamily) command.unshift('--seed-family');
                          if (collinear) command.unshift('--collinear');
                          let stageLog = "";
                          const start = performance.now();
                          const worker = new Worker('/mauve_web/static/browser/aligner-worker.mjs', {type: 'module'});
                          const message = await new Promise((resolve, reject) => {
                            const timeout = setTimeout(() => { worker.terminate(); reject(Error('Alignment timed out after 120 seconds')); }, 120000);
                            const finish = (fn, value) => { clearTimeout(timeout); worker.terminate(); fn(value); };
                            worker.onerror = e => finish(reject, Error(e.message));
                            worker.onmessage = ({data}) => {
                              if (data.type === 'log') stageLog += data.text;
                              if (data.type === 'done') finish(resolve, data);
                              if (data.type === 'error') finish(reject, Error(data.error));
                            };
                            worker.postMessage({inputs, command, threads});
                          });
                          const wallMs = performance.now() - start;
                          const hashes = {};
                          for (const [name, blob] of Object.entries(message.files)) {
                            hashes[name] = [...new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer()))].map(n=>n.toString(16).padStart(2,'0')).join('');
                          }
                          const stages = Object.fromEntries([...stageLog.matchAll(/MAUVE_STAGE (\\w+) ([\\d.]+) (\\d+)/g)].map(m => [m[1], {inclusive_ms: Number(m[2]), calls: Number(m[3])}]));
                          return {...message.metrics, wallMs, hashes, ...(Object.keys(stages).length ? {stages} : {})};
                        }''', {'kind': kind, 'genomes': args.genomes or 4, 'bases': args.bases, 'threads': threads, 'seedFamily': args.seed_family, 'collinear': args.collinear})
                        value['power_before'] = power_before
                        value['power_after'] = subprocess.check_output(['pmset', '-g', 'batt'], text=True).strip() if platform.system() == 'Darwin' else None
                        if expected is None:
                            expected = value['hashes']
                        assert set(value['hashes']) == {'xmfa', 'tree', 'backbone'}
                        assert value['hashes'] == expected, f'{kind}: artifact mismatch at {threads} threads'
                        results.append({'kind': kind, 'genomes': args.genomes or 4, 'bases': args.bases, 'repeat': repeat, 'seed_family': args.seed_family, 'collinear': args.collinear, **value})
                        print(f'{kind} {threads} threads: {value["wallMs"]:.1f} ms; artifacts match', flush=True)
                        args.output.write_text(json.dumps({'environment': info, 'results': results, 'note': 'Fresh workers and heaps per run. Wall time includes worker startup and input staging. Alternating thread order. Exact hashes, no normalization.'}, indent=2) + '\n')
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed-family', action='store_true')
    parser.add_argument('--collinear', action='store_true')
    parser.add_argument('--threaded-assets', type=Path, help='Optional experimental engine directory')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--threads', type=int, nargs='+', default=[1, 4, 8])
    parser.add_argument('--genomes', type=int)
    parser.add_argument('--bases', type=int, default=5000)
    parser.add_argument('--repeats', type=int, default=1)
    args = parser.parse_args()
    if 1 not in args.threads or any(n < 1 or n > 16 for n in args.threads):
        parser.error('--threads must include 1 and use values from 1 to 16')
    if args.repeats < 1 or args.bases < 1000 or (args.genomes is not None and not 2 <= args.genomes <= 128):
        parser.error('Use positive repeats, at least 1000 bases, and 2–128 genomes')
    run(args)
