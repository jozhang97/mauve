"""The shipped eight-strain E. coli demo works in both supported viewers."""
import json
from test_gene_analysis import analysis_site, site, browser, browser_app


def test_ecoli_demo_annotations_all_pairs_and_reuse(analysis_site, browser, tmp_path):
    mode, url = analysis_site
    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
    page.set_default_timeout(180000)
    errors, requests = [], []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('request', lambda r: requests.append(r.url))
    page.goto(url)
    if mode == 'static':
        page.wait_for_function('window.mauveReady === true')
    assert page.locator('#demo').inner_text() == '↗ Open E. coli demo'
    page.locator('#welcome-demo').click()
    page.wait_for_function('state.alignment?.genomes.length === 8 && state.sources.length === 8', timeout=180000)
    assert page.locator('#genome-count').inner_text() == '8'
    assert all(s['metadata']['records'][0]['topology'] == 'circular' for s in page.evaluate('state.sources'))
    names = page.evaluate('state.alignment.genomes.map(g => g.name)')
    assert names[0].startswith('E. coli MG-phbCAB-3-6') and names[-1].startswith('E. coli A12')
    assert page.evaluate('state.max') > 4_000_000
    page.locator('#run-gene-analysis').click()
    page.wait_for_function('document.querySelector("#gene-analysis-status").textContent.startsWith("Computed 28 pairs")', timeout=180000)
    assert page.locator('#gene-heatmap tbody tr').count() == 8
    with page.expect_download() as download:
        page.locator('#export-gene-json').click()
    download.value.save_as(tmp_path / 'ecoli-analysis.json')
    result = json.loads((tmp_path / 'ecoli-analysis.json').read_text())
    assert len(result['genomes']) == 8 and len(result['pairs']) == 28
    assert result['pan'] >= result['core'] > 1000
    assert all(g['genes'] > 3000 for g in result['genomes'])
    assert all(p['dcj'] is not None for p in result['pairs'])
    page.locator('#gene-analysis-panel').screenshot(path=str(tmp_path / 'ecoli-comparisons.png'))
    aid = page.evaluate('state.alignment.id')
    assert page.evaluate('async () => (await api("/api/demo", {method: "POST"})).id') == aid
    assert page.evaluate('async () => (await api("/api/alignments")).length') == 1
    page.reload()
    page.wait_for_function('state.alignment?.genomes.length === 8 && state.sources.length === 8', timeout=180000)
    if mode == 'static':
        assert sum(u.endswith('.gbk.gz') for u in requests) == 8
        assert sum(u.endswith('alignment.xmfa.gz') for u in requests) == 1
    assert not errors
    page.close()
