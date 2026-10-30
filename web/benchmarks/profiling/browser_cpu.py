"""Sample real Chrome worker stacks; run separately from timing benchmarks."""
import argparse
import asyncio
import functools
import http.server
import json
from pathlib import Path
import threading
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]

async def run(args):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def translate_path(self, path):
            relative = path.split('?', 1)[0].removeprefix('/mauve_web/static/wasm-threaded/')
            if relative in ('progressiveMauve.mjs', 'progressiveMauve.wasm'):
                return str(args.assets / relative)
            return super().translate_path(path)
        def end_headers(self):
            self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
            self.send_header('Cross-Origin-Embedder-Policy', 'credentialless')
            super().end_headers()
        def log_message(self, *args): pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            cdp = await browser.new_browser_cdp_session()
            pending, sessions, tasks, errors = {}, {}, [], []
            sequence = 0
            def received(event):
                msg = json.loads(event['message'])
                key = (event['sessionId'], msg.get('id'))
                if key in pending:
                    future = pending.pop(key)
                    if not future.done(): future.set_result(msg)
            cdp.on('Target.receivedMessageFromTarget', received)
            async def command(session, method, params=None):
                nonlocal sequence
                sequence += 1
                ident = sequence
                future = asyncio.get_running_loop().create_future()
                pending[(session, ident)] = future
                await cdp.send('Target.sendMessageToTarget', {'sessionId': session, 'message': json.dumps({'id': ident, 'method': method, 'params': params or {}})})
                reply = await asyncio.wait_for(future, 10)
                if 'error' in reply: raise RuntimeError(reply['error'])
                return reply.get('result', {})
            async def attach(info):
                try:
                    result = await cdp.send('Target.attachToTarget', {'targetId': info['targetId'], 'flatten': False})
                    session = result['sessionId']
                    await command(session, 'Profiler.enable')
                    await command(session, 'Profiler.setSamplingInterval', {'interval': 2000})
                    await command(session, 'Profiler.start')
                    sessions[session] = info
                except Exception as e: errors.append(str(e))
            def created(event):
                if event['targetInfo']['type'] == 'worker':
                    tasks.append(asyncio.create_task(attach(event['targetInfo'])))
            cdp.on('Target.targetCreated', created)
            await cdp.send('Target.setDiscoverTargets', {'discover': True})
            page = await browser.new_page()
            await page.goto(f'http://127.0.0.1:{server.server_port}/')
            alignment = asyncio.create_task(page.evaluate('''async () => {
              const {engineCase} = await import('/benchmarks/engine-cases.mjs');
              const inputs = engineCase('similar', 32, 100000, 12345).map(s => new Blob([`>genome\n${s}\n`]));
              const command = ['--output=/alignment.xmfa','--output-guide-tree=/guide.tree','--backbone-output=/alignment.backbone',...inputs.map((_,i)=>`/input-${i+1}.fa`)];
              window.profileWorker = new Worker('/mauve_web/static/browser/aligner-worker.mjs', {type:'module'});
              return await new Promise((resolve,reject)=>{
                profileWorker.onmessage=({data})=>{if(data.type==='done') resolve(data.metrics); if(data.type==='error') reject(Error(data.error));};
                profileWorker.onerror=e=>reject(Error(e.message));
                profileWorker.postMessage({inputs,command,threads:8});
              });
            }'''))
            # Capture preparation and most refinement; stop before the main worker exits.
            await asyncio.sleep(args.seconds)
            await asyncio.gather(*tasks)
            profiles = []
            for session, info in list(sessions.items()):
                try:
                    result = await command(session, 'Profiler.stop')
                    profiles.append({'target': info, **result})
                except Exception as e: errors.append(str(e))
            metrics = await asyncio.wait_for(alignment, 120)
            args.output.write_text(json.dumps({'browser': browser.version, 'sampling_interval_us': 2000, 'capture_seconds': args.seconds, 'profiles': profiles, 'errors': errors, 'metrics_not_for_benchmarking': metrics})+'\n')
            print(f'Captured {len(profiles)} workers; errors: {errors}', flush=True)
            await browser.close()
    finally:
        server.shutdown()
        server.server_close()

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--assets', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seconds', type=float, default=23)
    asyncio.run(run(p.parse_args()))
