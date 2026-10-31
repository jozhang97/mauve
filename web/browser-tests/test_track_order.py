"""DCJ ordering, unavailable values, and switching back to manual order."""
from test_gene_analysis import analysis_site, site, browser, browser_app


def test_reference_distance_order(analysis_site, browser):
    mode, url = analysis_site
    page=browser.new_page(viewport={'width':1440,'height':1100})
    page.goto(url)
    if mode=='static': page.wait_for_function('window.mauveReady === true')
    xmfa=''.join(f'> {i}:1-10 + g{i}.fa\nAAAAAAAAAA\n' for i in range(1,6))+'=\n'
    page.locator('#file').set_input_files({'name':'order.xmfa','mimeType':'text/plain','buffer':xmfa.encode()})
    page.wait_for_function('state.alignment?.genomes.length === 5')
    # Controlled metric input checks the viewer independently of metric calculation.
    page.evaluate('''() => {
      window.mauveGeneAnalysis = {result:{pairs:[
        {a:1,b:2,dcj:2},{a:1,b:3,dcj:0},{a:1,b:4,dcj:null},{a:1,b:5,dcj:2},
        {a:2,b:3,dcj:3},{a:2,b:4,dcj:0},{a:2,b:5,dcj:null}
      ]}};
      state.hidden.add(1);
    }''')
    page.locator('#track-sort').select_option('dcj')
    assert page.evaluate('state.order')==[1,3,2,5,4]
    assert page.evaluate('state.hidden.has(1)') is False
    assert 'DCJ distance: 0' in page.locator('.track-distance[data-genome="3"]').text_content()
    assert 'unavailable' in page.locator('.track-distance[data-genome="4"]').text_content()
    page.locator('#reference-genome').select_option('2')
    assert page.evaluate('state.order')==[2,4,1,3,5]
    page.locator('.track-settings summary').click()
    page.locator('.track-control[data-genome="1"] button').first.click()
    assert page.locator('#track-sort').input_value()=='manual'
    assert page.evaluate('state.order')==[2,1,4,3,5]
    page.locator('#track-sort').select_option('dcj')
    page.evaluate("() => { window.mauveGeneAnalysis.result=null; window.dispatchEvent(new Event('mauve-gene-analysis')); }")
    assert page.evaluate('state.order')==[2,1,3,4,5]
    assert page.locator('.track-distance[data-genome="1"]').text_content()=='Distance: unavailable'
    page.close()
