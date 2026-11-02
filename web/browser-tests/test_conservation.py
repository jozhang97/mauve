"""Profiles use the same numerical API in static and server modes."""
from test_gene_analysis import analysis_site, site, browser, browser_app


def test_worker_uses_build_version(site, browser):
    from urllib.parse import urlparse, parse_qs
    page = browser.new_page()
    workers = []
    page.on('worker', lambda worker: workers.append(worker.url))
    page.goto(site)
    page.wait_for_function('window.mauveReady === true')
    client = page.locator('script[src*="browser/client.js"]').get_attribute('src')
    version = parse_qs(urlparse(client).query).get('v')
    assert version, 'Static builds must invalidate cached browser code.'
    assert workers and parse_qs(urlparse(workers[0]).query).get('v') == version
    # Confirm that the versioned worker starts and accepts API requests.
    page.wait_for_function('window.mauveBrowser !== undefined')
    assert page.evaluate("async () => Array.isArray(await api('/api/alignments'))")
    page.close()


def test_conservation_profiles(analysis_site, browser, tmp_path):
    mode, url = analysis_site
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url)
    if mode == 'static':
        page.wait_for_function('window.mauveReady === true')
    rows = ['A'*100 + 'C'*100 + 'A'*100, 'A'*100 + 'T'*100 + 'A'*100, 'A'*100 + '-'*100 + 'A'*100]
    xmfa = ''.join(f'> {i+1}:1-{len(row.replace("-", ""))} {"-" if i == 1 else "+"} g{i+1}.fa\n{row}\n' for i, row in enumerate(rows)) + '=\n'
    page.locator('#file').set_input_files({'name': 'conservation.xmfa', 'mimeType': 'text/plain', 'buffer': xmfa.encode()})
    page.wait_for_function('state.alignment !== null')
    page.wait_for_function("document.querySelector('.conservation-mean') || conservationView.error")
    assert not errors, errors
    assert page.locator('.conservation-mean').count(), page.locator('#conservation-status').inner_text()
    assert page.locator('.conservation-profile').count() == 3
    assert page.locator('.identity-window').count() == 0
    before = page.locator('.conservation-profile[data-genome="1"] .conservation-mean').get_attribute('d')
    page.locator('#reference-genome').select_option('2')
    page.wait_for_function('!conservationView.pending')
    assert page.locator('.conservation-profile[data-genome="1"] .conservation-mean').get_attribute('d') == before
    # Inversion is expressed below the baseline, not by hatch marks.
    ys = page.locator('svg .block').evaluate_all('(nodes) => nodes.map(n => Number(n.getAttribute("y")))')
    assert ys[1] - ys[0] == 112 + 24
    assert page.locator('svg .block').first.get_attribute('fill') == 'white'
    page.locator('svg .block').first.click()
    page.wait_for_function('state.profile !== null')
    assert page.locator('.block-identity').count() == 3
    page.locator('#display-settings summary').click()
    page.locator('#backbone-file').set_input_files({'name': 'alignment.xmfa.bbcols', 'mimeType': 'text/plain', 'buffer': b'0 1 300 0 1\n'})
    page.wait_for_function('conservationView.revision === 1 && !conservationView.pending && conservationView.key === conservationView.desired?.key')
    assert 'Imported 1 backbone segments' in page.locator('#notice').inner_text()
    assert page.locator('.conservation-profile[data-genome="3"] .conservation-mean').get_attribute('data-backbone') == 'outside'
    page.locator('#show-conservation').uncheck()
    assert page.locator('.conservation-mean').count() == 0
    page.locator('#show-conservation').check()
    page.wait_for_selector('.conservation-mean')
    page.locator('#display-settings summary').click()
    page.evaluate('''() => {
      const original = api;
      api = async (...args) => { if (args[0].endsWith('/conservation')) await new Promise(resolve => setTimeout(resolve, 250)); return original(...args); };
      setRange(40, 80, false);
    }''')
    page.wait_for_function('conservationView.pending !== null')
    page.locator('#region').fill('90-120'); page.locator('#region-form button').click()
    page.locator('.export-menu summary').click()
    with page.expect_download() as download:
        page.locator('#export-svg').click()
    download.value.save_as(tmp_path / 'conservation.svg')
    assert 'conservation-mean' in (tmp_path / 'conservation.svg').read_text()
    page.locator('.export-menu summary').click()
    page.locator('#reset').click()
    page.wait_for_function('!conservationView.pending && conservationView.key === conservationView.desired?.key')
    page.locator('#overview-panel').screenshot(path=str(tmp_path / f'conservation-{mode}.png'))
    assert not errors
    page.close()


def test_real_demo_conservation_and_navigation(analysis_site, browser, tmp_path):
    import json
    import time
    mode, url = analysis_site
    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
    page.set_default_timeout(120000)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url)
    if mode == 'static':
        page.wait_for_function('window.mauveReady === true')
    started = time.monotonic()
    page.locator('#welcome-demo').click()
    page.wait_for_function('state.alignment?.genomes.length === 8 && state.sources.length === 8')
    page.wait_for_function('conservationView.data && conservationView.key === conservationView.desired?.key && !conservationView.pending')
    initial = time.monotonic() - started
    assert page.locator('.conservation-profile').count() >= 8
    assert page.locator('.conservation-mean[data-backbone="outside"]').count() > 0
    page.locator('#overview-panel').screenshot(path=str(tmp_path / f'ecoli-conservation-{mode}.png'))
    started = time.monotonic()
    page.evaluate('setRange(100000, 130000, false)')
    page.wait_for_function('conservationView.key === conservationView.desired?.key && !conservationView.pending')
    zoom = time.monotonic() - started
    assert page.locator('.conservation-mean').count() > 0
    assert 'NaN' not in page.locator('#tracks').inner_html()
    # A queued old response must not overwrite a newer viewport; export waits too.
    page.evaluate('() => { setRange(200000,230000,false); setRange(300000,330000,false); setRange(400000,430000,false); }')
    page.wait_for_function('conservationView.key === conservationView.desired?.key && !conservationView.pending')
    assert page.evaluate('state.start') == 400000
    page.locator('#overview-panel').screenshot(path=str(tmp_path / f'ecoli-conservation-zoom-{mode}.png'))
    (tmp_path / 'timings.json').write_text(json.dumps({'mode': mode, 'demo_load_and_index_seconds': initial, 'cached_zoom_seconds': zoom}))
    assert not errors
    page.close()
