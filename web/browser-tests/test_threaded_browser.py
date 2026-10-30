"""Exercise the deployed Pages isolation path, fallback, errors and cancellation."""
import time
import pytest
from test_browser import site, browser


@pytest.mark.parametrize('service_workers,threads', [('allow', 8), ('block', 1)])
def test_pages_selects_engine_and_completes_real_alignment(site, browser, service_workers, threads):
    context = browser.new_context(service_workers=service_workers)
    page = context.new_page()
    page.goto(site)
    page.wait_for_function("document.querySelector('#compute-status').textContent !== 'Starting local compute…'")
    engine = page.evaluate("window.mauveBrowser.request('/api/engine')")
    expected = min(threads, page.evaluate('navigator.hardwareConcurrency'))
    assert engine['threads'] == expected
    assert f'{expected} CPU thread' in page.locator('#compute-status').inner_text()
    assert page.evaluate('crossOriginIsolated') == (service_workers == 'allow')
    result = page.evaluate('''async () => {
      let seed = 12345, sequence = '';
      for (let i=0; i<10000; i++) {seed=(Math.imul(seed,1664525)+1013904223)>>>0; sequence+='ACGT'[seed>>>30];}
      const inputs = Array.from({length:4}, (_,i)=>new Blob([`>genome\n${sequence.slice(0,100+i)}A${sequence.slice(101+i)}\n`]));
      const worker = new Worker(new URL('./static/browser/aligner-worker.mjs', location.href), {type:'module'});
      try {
        const message = await new Promise((resolve,reject)=>{
          const timer=setTimeout(()=>{worker.terminate();reject(Error('Worker timed out'));},30000);
          worker.onerror=e=>{clearTimeout(timer);reject(Error(e.message));};
          worker.onmessage=({data})=>{if(data.type==='done'){clearTimeout(timer);resolve(data);}if(data.type==='error'){clearTimeout(timer);reject(Error(data.error));}};
          worker.postMessage({inputs,command:['--output=/alignment.xmfa','--output-guide-tree=/guide.tree','--backbone-output=/alignment.backbone',...inputs.map((_,i)=>`/input-${i+1}.fa`)]});
        });
        return {threads:message.metrics.threads, xmfa:await message.files.xmfa.text()};
      } finally {worker.terminate();}
    }''')
    assert result['threads'] == expected
    assert '#Sequence4File' in result['xmfa']
    context.close()


def test_cancelling_alignment_terminates_descendant_workers(site, browser):
    context = browser.new_context()
    page = context.new_page()
    page.goto(site)
    page.wait_for_function('crossOriginIsolated && !!window.mauveBrowser')
    cdp = browser.new_browser_cdp_session()
    def targets():
        return {t['targetId'] for t in cdp.send('Target.getTargets')['targetInfos'] if t['type'] == 'worker'}
    before = targets()
    page.evaluate('''async () => {
      let seed=12345, sequence='';
      for(let i=0;i<100000;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;sequence+='ACGT'[seed>>>30];}
      const inputs=Array.from({length:32},(_,i)=>new Blob([`>genome\n${sequence.slice(0,100+i)}A${sequence.slice(101+i)}\n`]));
      window.testAligner=new Worker(new URL('./static/browser/aligner-worker.mjs',location.href),{type:'module'});
      await new Promise((resolve,reject)=>{
        const timer=setTimeout(()=>{testAligner.terminate();reject(Error('Worker startup timed out'));},30000);
        testAligner.onerror=e=>{clearTimeout(timer);reject(Error(e.message));};
        testAligner.onmessage=({data})=>{if(data.type==='log'){clearTimeout(timer);resolve();}if(data.type==='error'){clearTimeout(timer);reject(Error(data.error));}};
        testAligner.postMessage({inputs,threads:4,command:['--output=/alignment.xmfa',...inputs.map((_,i)=>`/input-${i+1}.fa`)]});
      });
    }''')
    created = targets() - before
    assert len(created) >= 5  # alignment host plus four pthread workers
    page.evaluate('testAligner.terminate()')
    deadline = time.monotonic() + 5
    while targets() & created and time.monotonic() < deadline:
        page.wait_for_timeout(50)
    assert not targets() & created
    cdp.detach()
    context.close()


def test_threaded_engine_reports_invalid_command_without_hanging(site, browser):
    context = browser.new_context()
    page = context.new_page()
    page.goto(site)
    page.wait_for_function('crossOriginIsolated && !!window.mauveBrowser')
    message = page.evaluate('''async () => {
      const worker = new Worker(new URL('./static/browser/aligner-worker.mjs', location.href), {type:'module'});
      try {
        return await new Promise((resolve,reject)=>{
          const timer=setTimeout(()=>{worker.terminate();reject(Error('Exit notification timed out'));},30000);
          worker.onerror=e=>{clearTimeout(timer);reject(Error(e.message));};
          worker.onmessage=({data})=>{if(data.type==='error'||data.type==='done'){clearTimeout(timer);resolve(data);}};
          worker.postMessage({inputs:[], command:['--invalid-mauve-test-option'], threads:4});
        });
      } finally {worker.terminate();}
    }''')
    assert message['type'] == 'error'
    assert 'exited with status' in message['error']
    context.close()
