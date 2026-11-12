"""Bundled demos retain annotations and work in both supported viewers."""
import json
import pytest
from test_gene_analysis import analysis_site, site, browser, browser_app


@pytest.mark.parametrize('organism,count,min_genes,first,last', [
    ('ecoli', 8, 3000, 'E. coli MG-phbCAB-3-6', 'E. coli A12'),
    ('hpylori', 6, 1000, 'H. pylori 26695', 'H. pylori Shi470'),
    ('bsubtilis', 6, 3000, 'B. subtilis 168', 'B. subtilis RO-NN-1'),
])
def test_demo_annotations_all_pairs_and_reuse(analysis_site, browser, tmp_path, organism, count, min_genes, first, last):
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
    page.locator('#welcome-demo' + ('' if organism == 'ecoli' else '-' + organism)).click()
    page.wait_for_function(f'state.alignment?.genomes.length === {count} && state.sources.length === {count}', timeout=180000)
    assert page.locator('#genome-count').inner_text() == str(count)
    assert all(s['metadata']['records'][0]['topology'] == 'circular' for s in page.evaluate('state.sources'))
    names = page.evaluate('state.alignment.genomes.map(g => g.name)')
    assert names[0].startswith(first) and names[-1].startswith(last)
    assert page.evaluate('state.max') > (4_000_000 if organism == 'ecoli' else 1_500_000)
    pairs = count * (count - 1) // 2
    page.locator('#run-gene-analysis').click()
    page.wait_for_function(f'document.querySelector("#gene-analysis-status").textContent.startsWith("Computed {pairs} pairs")', timeout=180000)
    assert page.locator('#gene-heatmap tbody tr').count() == count
    with page.expect_download() as download:
        page.locator('#export-gene-json').click()
    download.value.save_as(tmp_path / 'demo-analysis.json')
    result = json.loads((tmp_path / 'demo-analysis.json').read_text())
    assert len(result['genomes']) == count and len(result['pairs']) == pairs
    assert result['pan'] >= result['core'] > (1000 if organism == 'ecoli' else 500)
    assert all(g['genes'] > min_genes for g in result['genomes'])
    assert all(p['dcj'] is not None for p in result['pairs'])
    if organism == 'hpylori':
        assert result['essentiality_source']['id'] == 'chalker-2001-hpylori'
        assert result['essentiality_matched_copies'] == 40
        assert sum(m['essentiality']['status'] == 'essential' for f in result['families'] for m in f['members']) == 31
        page.wait_for_function('window.mauveOriginAnalysis?.result?.eligible.length === 6')
        assert page.evaluate('window.mauveOriginAnalysis.result.genes.length') > 8000
        assert page.locator('#origin-distances svg rect').count() > 0
        assert 'oriC1' in page.locator('#origin-analysis-status').inner_text()
        assert page.evaluate('window.mauveOriginAnalysis.result.origins.every(o => o.origin > 1 && o.regions.length > 0)')

    if organism == 'bsubtilis':
        assert result['essentiality_source']['id'] == 'koo-2017-bsubtilis'
        essential = [m for f in result['families'] for m in f['members'] if m['essentiality']['status'] == 'essential']
        assert sum(m['genome_id'] == 1 for m in essential) == 257
        assert len(essential) > 1000
        assert any(m['essentiality']['status'] == 'unknown' for f in result['families'] for m in f['members'])
        page.wait_for_function('window.mauveOriginAnalysis?.result?.eligible.length === 6')
        assert page.evaluate('window.mauveOriginAnalysis.result.genes.length') > 20000
        assert page.locator('#origin-distances svg rect').count() > 0
        assert 'oriC2' in page.locator('#origin-analysis-status').inner_text()
        assert page.evaluate('window.mauveOriginAnalysis.result.origins.every(o => o.origin > 1 && o.regions.length > 0)')

    page.locator('#gene-analysis-panel').screenshot(path=str(tmp_path / 'demo-comparisons.png'))
    aid = page.evaluate('state.alignment.id')
    assert page.evaluate('async organism => (await api(`/api/demo?organism=${organism}`, {method: "POST"})).id', organism) == aid
    assert page.evaluate('async () => (await api("/api/alignments")).length') == 1
    page.reload()
    page.wait_for_function(f'state.alignment?.genomes.length === {count} && state.sources.length === {count}', timeout=180000)
    if mode == 'static':
        assert sum(u.endswith('.gbk.gz') for u in requests) == count
        assert sum(u.endswith('alignment.xmfa.gz') for u in requests) == 1
        if organism == 'bsubtilis':
            # Simulate a saved demo from before B. subtilis origins were bundled.
            page.evaluate('''async aid => {
              const {Store} = await import('./static/browser/store.mjs');
              const store = await new Store().open();
              const source = await store.get('annotations', [aid, 1]);
              source.metadata.demo_evidence_version = 1;
              delete source.metadata.records[0].replication_origin;
              await store.put('annotations', [aid, 1], source);
              store.db.close();
              await api('/api/demo?organism=bsubtilis', {method:'POST'});
              const sources = await api(`/api/alignments/${aid}/annotations`);
              if (sources[0].metadata.demo_evidence_version !== 2 || sources[0].metadata.records[0].replication_origin !== 1751)
                throw Error('Saved demo origins did not refresh');
            }''', aid)
            assert sum(u.endswith('alignment.xmfa.gz') for u in requests) == 1
    other = 'ecoli' if organism == 'hpylori' else 'hpylori'
    other_id = page.evaluate('async organism => (await api(`/api/demo?organism=${organism}`, {method: "POST"})).id', other)
    assert other_id != aid
    page.locator('#demo-hpylori' if other == 'hpylori' else '#demo').click()
    page.wait_for_function('id => state.alignment?.id === id && state.sources.length === state.alignment.genomes.length', arg=other_id)
    assert page.evaluate('window.mauveGeneAnalysis.result === null')
    assert page.locator('#origin-results').is_hidden()
    assert all(name.startswith('H. pylori' if other == 'hpylori' else 'E. coli') for name in page.evaluate('state.alignment.genomes.map(g=>g.name)'))
    assert page.evaluate('async () => (await api("/api/alignments")).length') == 2
    assert not errors
    page.close()
