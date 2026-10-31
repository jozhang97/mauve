"""Core blocks use actual gene segments and refresh when results change."""
from test_gene_analysis import analysis_site, site, browser, browser_app


def test_core_block_filter(analysis_site, browser):
    mode, url = analysis_site
    page = browser.new_page()
    page.goto(url)
    if mode == 'static':
        page.wait_for_function('window.mauveReady === true')
    xmfa = ''.join(''.join(f'> {i}:{start}-{start+9} + g{i}.fa\nAAAAAAAAAA\n' for i in [1, 2]) + '=\n' for start in [1, 11, 21])
    page.locator('#file').set_input_files({'name': 'core.xmfa', 'mimeType': 'text/plain', 'buffer': xmfa.encode()})
    page.wait_for_function('state.blocks.length === 3')
    page.evaluate('''() => {
      window.mauveGeneAnalysis = {result:{core:1, genomes:[{id:1},{id:2}], pairs:[], families:[
        {genomes:2, members:[1,2].map(genome_id => ({genome_id,id:1,start:1,end:30,parts:[{start:1,end:2},{start:29,end:30}]}))}
      ]}};
    }''')
    page.locator('#display-settings summary').click()
    page.evaluate('selectBlock(2)')
    page.locator('#isolate-block').check()
    page.evaluate('setRange(11, 20)')
    page.locator('#core-genes-only').check()
    assert not page.locator('#isolate-block').is_checked()
    assert page.locator('.block').count() > 0
    assert page.evaluate('visibleBlocks().map(b => b.id)') == [1, 3]
    assert page.locator('#block-list strong').all_text_contents() == ['Block 1', 'Block 3']
    assert page.locator('.block[data-block-id="2"]').count() == 0
    page.locator('#min-columns').fill('100')
    page.locator('#min-columns').dispatch_event('change')
    assert page.evaluate('visibleBlocks().length') == 0
    assert 'other display filters hide them' in page.locator('#map-feedback-text').inner_text()
    page.locator('#clear-map-filters').click()
    assert page.locator('#core-genes-only').is_checked()
    assert page.evaluate('visibleBlocks().length') == 2
    page.locator('#core-genes-only').uncheck()
    assert page.evaluate('visibleBlocks().length') == 3
    page.locator('#core-genes-only').check()
    page.evaluate("() => { window.mauveGeneAnalysis.result=null; window.dispatchEvent(new Event('mauve-gene-analysis')); }")
    assert page.evaluate('visibleBlocks().length') == 3
    assert 'filter pending' in page.locator('#map-feedback-text').inner_text()
    assert 'No blocks match' not in page.locator('#map-feedback-text').inner_text()
    page.evaluate("""() => {
      document.querySelector('#run-gene-analysis').disabled = true;
      window.mauveGeneAnalysis.status = 'Matching genes: block 1 of 3';
      window.dispatchEvent(new Event('mauve-gene-analysis-status'));
    }""")
    assert 'Matching genes: block 1 of 3' in page.locator('#map-feedback-text').inner_text()
    assert page.locator('#clear-map-filters').is_disabled()
    assert page.locator('#tracks').get_attribute('aria-busy') == 'true'
    page.evaluate("""() => {
      document.querySelector('#run-gene-analysis').disabled = false;
      window.mauveGeneAnalysis.result = {core:0, genomes:[{id:1},{id:2}], pairs:[], families:[]};
      window.dispatchEvent(new Event('mauve-gene-analysis'));
    }""")
    assert page.evaluate('visibleBlocks().length') == 0
    assert 'No blocks contain core-family genes' in page.locator('#map-feedback-text').inner_text()
    assert page.locator('#tracks').get_attribute('aria-busy') == 'false'
    page.locator('#clear-map-filters').click()
    assert not page.locator('#core-genes-only').is_checked()
    assert page.evaluate('visibleBlocks().length') == 3
    page.close()
