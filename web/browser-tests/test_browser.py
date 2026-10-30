"""Static-only integration checks: python -m pytest browser-tests/test_browser.py -q."""
import functools
import http.server
import importlib.util
import os
from pathlib import Path
import threading
import socketserver
import time

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp('pages')
    spec = importlib.util.spec_from_file_location('build_pages', ROOT / 'build_pages.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.build(root / 'mauve')
    class Server(http.server.ThreadingHTTPServer):
        def server_bind(self):
            socketserver.TCPServer.server_bind(self)
            self.server_name = 'localhost'
            self.server_port = self.server_address[1]
    server = Server(('127.0.0.1', 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}/mauve/'
    server.shutdown(); server.server_close()

@pytest.fixture
def browser():
    with sync_playwright() as p:
        path = os.environ.get('MAUVE_CHROME_PATH')
        if not path and Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome').exists():
            path = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        browser = p.chromium.launch(headless=os.environ.get('MAUVE_HEADFUL') != '1', **({'executable_path': path} if path else {}))
        yield browser
        browser.close()

def test_static_viewer_import_persistence_exports_and_job(site, browser, tmp_path):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    requests, errors = [], []
    page.on('request', lambda r: requests.append(r.url))
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(site)
    page.wait_for_function("window.mauveReady === true")
    page.locator('#welcome-demo').click()
    page.wait_for_selector('svg .feature')
    assert page.locator('#genome-count').inner_text() == '2'
    assert '2,000 canonical aligned bases' in page.locator('#annotation-status').inner_text()
    page.locator('#gene-query').fill('TEL01L-TR'); page.locator('#feature-search button').click()
    page.locator('#feature-results button').first.click()
    assert 'TEL01L-TR' in page.locator('#feature-detail').inner_text()
    page.locator('#block-list button').first.click(); page.wait_for_selector('.base-row')
    page.locator('.export-menu summary').click()
    for control, name in [('#export-fasta', 'block.fasta'), ('#export-blocks', 'blocks.tsv'), ('#export-svg', 'view.svg')]:
        with page.expect_download() as download: page.locator(control).click()
        download.value.save_as(tmp_path / name)
        assert (tmp_path / name).stat().st_size > 50
    page.reload(); page.wait_for_selector('svg .feature')
    assert page.locator('#library button').count() == 1
    # Real native engine in a nested browser worker, with no HTTP API.
    page.locator('#new-alignment').click()
    sequence = page.evaluate("""() => { let s=12345,out='';for(let i=0;i<5000;i++){s=(Math.imul(s,1664525)+1013904223)>>>0;out+='ACGT'[s>>>30];} return out; }""")
    page.locator('#sequence-files').set_input_files([
        {'name': 'first.fa', 'mimeType': 'text/plain', 'buffer': ('>first\n'+sequence).encode()},
        {'name': 'second.fa', 'mimeType': 'text/plain', 'buffer': ('>second\n'+sequence[:2500]+'A'+sequence[2501:]).encode()},
    ])
    page.wait_for_function("document.querySelector('#staged-inputs').children.length === 2")
    page.locator('#submit-job').click()
    page.wait_for_function("document.querySelector('#job-status').textContent === 'succeeded'", timeout=60000)
    assert page.locator('#job-artifacts a').count() == 5
    page.locator('#open-result').click(); page.locator('#block-list button').first.click(); page.wait_for_selector('.base-row')
    assert page.locator('#genome-count').inner_text() == '2'
    page.reload(); page.wait_for_selector('svg .block')
    assert page.locator('#library button').count() == 2
    assert not any('/api/' in u for u in requests)
    assert all(u.startswith(site) or u.startswith('blob:') for u in requests)
    assert not errors


def test_map_links_preserve_crossings_and_viewport_boundaries(site, browser):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.goto(site)
    page.wait_for_function("window.mauveReady === true")
    page.wait_for_function("typeof render === 'function'")
    result = page.evaluate("""() => {
      state.alignment = {genomes: [1, 2].map(id => ({id, name: `Genome ${id}`, extent: 1000}))};
      state.order = [1, 2]; state.start = 100; state.end = 199;
      state.selected = null; state.detail = null; state.profile = null;
      state.sources = []; state.features = []; state.hidden.clear();
      clearBlockFilters(); $('links').checked = true;
      $('welcome').hidden = true; $('explorer').hidden = false;
      const ranges = [
        [[1, 20], [30, 40]],       // wholly left
        [[201, 220], [230, 240]],  // wholly right
        [[120, 140], [150, 170]],  // visible endpoints
        [[1, 20], [230, 240]],     // crossing, both endpoints outside
        [[230, 240], [1, 20]],     // crossing, inverted member
        [[70, 99], [80, 99]],      // touches left boundary
        [[200, 220], [200, 240]],  // touches right boundary
      ];
      state.blocks = ranges.map((pair, i) => ({id: i + 1, columns: 20,
        members: pair.map(([start, end], j) => ({genome_id: j + 1, start, end,
          strand: i === 4 && j === 1 ? '-' : '+'}))}));
      const paths = () => [...document.querySelectorAll('.alignment-links path')];
      render();
      const colorsBefore = paths().map(p => p.getAttribute('fill'));
      const crossingPaths = paths().slice(1, 3).map(p => p.getAttribute('d'));
      state.order.reverse(); render();
      const colorsAfter = paths().map(p => p.getAttribute('fill'));
      state.hidden.add(1); render(); const hiddenCount = paths().length;
      state.hidden.clear();
      // Pan with cached metadata, then replace one block's members array.
      state.start = 300; state.end = 399; render(); const pannedCount = paths().length;
      state.blocks[0].members = state.blocks[0].members.map(m => ({...m, start: 320, end: 340}));
      render(); const replacedCount = paths().length;
      $('links').checked = false; render();
      return {colorsBefore, colorsAfter, expected: [3,4,5,6,7].map(color),
        crossingPaths, hiddenCount, pannedCount, replacedCount, disabledCount: paths().length};
    }""")
    assert result['colorsBefore'] == result['expected']
    assert result['colorsAfter'] == result['expected']
    assert all('NaN' not in path for path in result['crossingPaths'])
    assert result['hiddenCount'] == result['pannedCount'] == result['disabledCount'] == 0
    assert result['replacedCount'] == 1
    page.close()


def test_gpu_parity_large_data_and_cpu_fallback(site, browser):
    page = browser.new_page(); page.goto(site)
    page.wait_for_function("window.mauveReady === true")
    result = page.evaluate("""async () => {
      const {Accelerator} = await import('./static/browser/gpu.mjs');
      const {pairCounts} = await import('./static/browser/core.mjs');
      const gpu = new Accelerator(); await gpu.ready;
      const n=1500003,a=new Uint8Array(n),b=new Uint8Array(n),alphabet=new TextEncoder().encode('ACGTN-RY');
      for(let i=0;i<n;i++){a[i]=alphabet[i%8];b[i]=alphabet[(i+(i%17===0?1:0))%8];}
      const width=Math.ceil(n/100), expected=pairCounts(a,b,width);
      const before=performance.now();const actual=await gpu.counts(a,b,width); const elapsed=performance.now()-before;
      const mode=gpu.mode;gpu.device?.destroy();gpu.device=null;
      const fallback=await gpu.counts(a,b,width);
      return {mode,elapsed,correct:expected.every((v,i)=>v===actual[i]&&v===fallback[i]),reason:gpu.reason};
    }""")
    print(result)
    assert result['correct']
    if os.environ.get('MAUVE_HEADFUL') == '1':
        assert result['mode'] == 'WebGPU + CPU worker', result


def test_failed_import_atomicity_and_cancel(site, browser):
    page = browser.new_page(); page.goto(site)
    page.wait_for_function("window.mauveReady === true")
    result = page.evaluate("""async () => {
      const req = (p,o) => mauveBrowser.request(p,o);
      let failed=false;
      try { await req('/api/alignments?name=bad', {method:'POST',body:new Blob(['> 1:1-3 +\\nACG\\n=\\n> 1:1-4 +\\nAC\\n='])}); } catch { failed=true; }
      const library=await req('/api/alignments');
      let seed=45,s='';for(let i=0;i<100000;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;s+='ACGT'[seed>>>30];}
      const ids=[];for(let i=0;i<3;i++){const v=await req('/api/inputs?name='+i+'.fa',{method:'POST',body:new Blob(['>a\\n'+s])});ids.push(v.id);}
      const job=await req('/api/jobs',{method:'POST',body:JSON.stringify({input_ids:ids})});
      await req('/api/jobs/'+job.id+'/cancel',{method:'POST'});
      return {failed,library,id:job.id};
    }""")
    assert result['failed'] and result['library'] == []
    page.wait_for_function("async id => (await mauveBrowser.request('/api/jobs/'+id)).status === 'cancelled'", arg=result['id'])


def test_interrupted_job_can_rerun_in_new_tab(site, browser):
    # Request interception needs the serial fallback, without a service worker.
    context = browser.new_context(service_workers='block')
    context.route('**/progressiveMauve.wasm', lambda route: None)
    page = context.new_page(); page.goto(site)
    page.wait_for_function("window.mauveReady === true")
    job = page.evaluate("""async () => {
      let seed=12345,s='';for(let i=0;i<5000;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;s+='ACGT'[seed>>>30];}
      const ids=[];for(let i=0;i<2;i++)ids.push((await mauveBrowser.request('/api/inputs?name='+i+'.fa',{method:'POST',body:new Blob(['>a\\n'+s])})).id);
      return mauveBrowser.request('/api/jobs',{method:'POST',body:JSON.stringify({input_ids:ids})});
    }""")
    page.wait_for_function("async id => (await mauveBrowser.request('/api/jobs/'+id)).status === 'running'", arg=job['id'])
    page.close(); context.unroute('**/progressiveMauve.wasm')
    page = context.new_page(); page.goto(site)
    page.wait_for_function("window.mauveReady === true")
    page.wait_for_function("async id => (await mauveBrowser.request('/api/jobs')).find(j=>j.id===id)?.status === 'interrupted'", arg=job['id'])
    rerun = page.evaluate("options => mauveBrowser.request('/api/jobs',{method:'POST',body:JSON.stringify(options)})", job['spec']['options'])
    page.wait_for_function("async id => (await mauveBrowser.request('/api/jobs/'+id)).status === 'succeeded'", arg=rerun['id'], timeout=30000)
    context.close()


def test_column_selection_preserves_keyboard_and_accessibility_state(site, browser):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.goto(site)
    page.wait_for_function("window.mauveReady === true")
    page.wait_for_function("typeof renderBases === 'function'")
    page.evaluate("""() => {
      state.alignment = {genomes: [1, 2].map(id => ({id, name: `Genome ${id}`, extent: 8}))};
      state.order = [1, 2]; state.hidden.clear(); state.profile = null;
      state.detail = {offset: 0, columns: 8, members: [1, 2].map(genome_id => ({
        genome_id, start: 1, end: 8, strand: '+', bases: genome_id === 1 ? 'ACGTACGT' : 'ATGTTCGT',
        positions: Array.from({length: 8}, (_, i) => i + 1)}))};
      $('welcome').hidden = true; $('explorer').hidden = false;
      $('differences-only').checked = false; state.activeColumn = 0; renderBases();
    }""")
    def check(column, rows=2):
        assert page.locator('#bases .base.active-column').count() == rows
        assert page.locator('#bases .base[aria-pressed="true"]').count() == rows
        assert page.locator('#bases .base[tabindex="0"]').count() == rows
        assert page.evaluate("""column => [...document.querySelectorAll('#bases .base')].every(base => {
          const active = Number(base.dataset.column) === column;
          return base.classList.contains('active-column') === active &&
            base.getAttribute('aria-pressed') === String(active) && base.tabIndex === (active ? 0 : -1);
        })""", column)
    check(0)
    page.locator('#bases .base[data-genome="1"][data-column="2"]').click()
    check(2)
    page.keyboard.press('ArrowRight')
    check(3)
    page.evaluate("$('differences-only').checked = true; renderBases()")
    check(1)
    page.locator('#bases .base[data-genome="1"][data-column="1"]').focus()
    page.keyboard.press('ArrowRight')
    check(4)
    page.keyboard.press('ArrowRight')
    check(4)
    page.evaluate("state.hidden.add(2); renderBases()")
    check(4, 1)
    page.evaluate("state.hidden.add(1); renderBases()")
    assert page.locator('#bases .base').count() == 0
    page.evaluate("state.hidden.clear(); $('differences-only').checked = false; renderBases()")
    check(4)


def test_map_block_handlers_preserve_click_keys_and_double_click(site, browser):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.goto(site)
    page.wait_for_function("window.mauveReady === true")
    page.wait_for_function("typeof render === 'function'")
    result = page.evaluate("""() => {
      state.alignment = {genomes: [{id: 1, name: 'Genome', extent: 1000}]};
      state.order = [1]; state.start = 1; state.end = 1000; state.max = 1000;
      state.selected = null; state.detail = null; state.profile = null;
      state.sources = []; state.features = []; state.hidden.clear();
      state.blocks = [{id: 7, columns: 41, members: [{genome_id: 1, start: 100, end: 140, strand: '-'}]}];
      clearBlockFilters(); $('welcome').hidden = true; $('explorer').hidden = false; render();
      const selections = [], ranges = [], savedSelect = selectBlock, savedRange = setRange;
      selectBlock = id => selections.push(id); setRange = (...args) => ranges.push(args);
      const block = document.querySelector('#tracks .block');
      const event = (type, properties = {}) => type === 'keydown'
        ? new KeyboardEvent(type, {bubbles: true, cancelable: true, ...properties})
        : new MouseEvent(type, {bubbles: true, cancelable: true, ...properties});
      block.dispatchEvent(event('click'));
      block.querySelector('title').dispatchEvent(event('click'));
      const enter = event('keydown', {key: 'Enter'}), space = event('keydown', {key: ' '});
      block.dispatchEvent(enter); block.dispatchEvent(space);
      block.dispatchEvent(event('keydown', {key: 'ArrowLeft'}));
      block.dispatchEvent(event('dblclick'));
      block.parentNode.dispatchEvent(event('click'));
      selectBlock = savedSelect; setRange = savedRange;
      return {selections, ranges, enter: enter.defaultPrevented, space: space.defaultPrevented};
    }""")
    assert result['selections'] == [7, 7, 7, 7]
    assert result['ranges'] == [[95.2, 144.8]]
    assert result['enter'] and result['space']
