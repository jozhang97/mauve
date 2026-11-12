"""Replication overlays use imported origins and survive display reversal."""
from io import StringIO
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord
from test_gene_analysis import analysis_site, site, browser, browser_app


def test_replication_overlay(analysis_site, browser):
    mode, url = analysis_site
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(url)
    if mode == 'static':
        page.wait_for_function('window.mauveReady === true')
    dna = 'G' * 100 + 'C' * 100
    xmfa = '> 1:1-200 + first.fa\n' + dna + '\n=\n'
    page.locator('#file').set_input_files({'name': 'rep.xmfa', 'mimeType': 'text/plain', 'buffer': xmfa.encode()})
    page.wait_for_function('state.blocks.length === 1')
    record = SeqRecord(Seq(dna), id='chr', annotations={'molecule_type': 'DNA', 'topology': 'circular'})
    record.features = [SeqFeature(SimpleLocation(0, 2), type='rep_origin'),
                       SeqFeature(SimpleLocation(10, 30, strand=1), type='CDS'),
                       SeqFeature(SimpleLocation(110, 130, strand=1), type='CDS')]
    out = StringIO()
    SeqIO.write(record, out, 'genbank')
    page.locator('#annotation-file').set_input_files({'name': 'rep.gbk', 'mimeType': 'text/plain', 'buffer': out.getvalue().encode()})
    page.wait_for_function('state.sources.length === 1')
    page.evaluate('selectBlock(1)')
    page.wait_for_function('state.features.length === 3')
    page.evaluate("() => { document.querySelector('#show-replication').checked = true; document.querySelector('#show-gc-skew').checked = true; render(); }")
    assert page.locator('.replication-track').count() == 1
    assert 'ter ≈' in page.locator('.replication-track').text_content()
    assert page.evaluate("state.features.filter(f=>f.type==='CDS').map(replicationClass)") == ['co-oriented', 'head-on']
    # Exercise the panel with a minimal family result; the eight-genome demo
    # separately verifies the complete matching workflow.
    page.evaluate("""() => {
      const genes=state.features.filter(f=>f.type==='CDS');
      window.mauveGeneAnalysis={result:{genomes:state.alignment.genomes,core:2,
        families:genes.map((g,i)=>({id:'F'+i,genomes:1,members:[g]}))}};
      window.dispatchEvent(new Event('mauve-gene-analysis'));
    }""")
    page.wait_for_function('window.mauveOriginAnalysis?.result?.genes.length === 2')
    assert page.locator('#origin-fractions tbody tr').count() == 4
    assert page.locator('#origin-fractions tbody tr').first.locator('td').all_text_contents() == ['core', '2', '50.0% (1)', '50.0% (1)', '0']
    assert page.locator('#origin-distances svg rect').count() == 60
    page.locator('#origin-histogram-scale').select_option('percent')
    assert page.locator('#origin-distances svg').get_attribute('aria-label').endswith('percent within each gene set')
    assert page.locator('#origin-distances rect').evaluate_all("nodes=>nodes.reduce((sum,n)=>sum+Number(n.dataset.value),0)") == 100
    page.locator('#origin-histogram-scale').select_option('count')
    assert page.locator('#origin-distances rect').evaluate_all("nodes=>nodes.reduce((sum,n)=>sum+Number(n.dataset.value),0)") == 2
    assert page.locator('#origin-ranges svg rect').count() == 40
    assert '0 core families compared;' in page.locator('#origin-range-status').text_content()
    assert '2 unavailable' in page.locator('#origin-range-status').text_content()
    assert page.locator('#origin-arm-histogram').count() == 0
    assert 'Maximum circular separation' in page.locator('#origin-ranges svg').get_attribute('aria-label')
    page.locator('#origin-range-metric').select_option('distance')
    assert 'Distance-to-oriC range' in page.locator('#origin-ranges svg').get_attribute('aria-label')
    page.locator('#origin-range-metric').select_option('position')
    page.locator('#origin-unit').select_option('kb')
    page.locator('#origin-genome').select_option('1')
    assert page.locator('#origin-analysis-status').text_content().startswith('Origins available for 1/1')
    page.locator('#start-at-oric').click()
    assert page.locator('#align-tracks').is_checked()
    assert not page.locator('#orient-tracks').is_checked()
    assert page.evaluate('trackOffset(1)') == 0
    page.evaluate('state.sources[0].metadata.records[0].replication_origin = 76')
    page.locator('#start-at-oric').click()
    assert page.evaluate('trackOffset(1)') == 75
    assert page.evaluate('trackCopies(76,76,1).some(copy => Math.abs(orientedEdge(76,1)+copy-trackOffset(1)-state.start)<0.001)')
    page.evaluate('state.sources[0].metadata.records[0].replication_origin = 1')
    page.locator('#start-at-oric').click()
    assert page.evaluate('state.sources[0].metadata.records[0].gc_skew[0].value') == 1
    colors = page.locator('.feature').evaluate_all("nodes=>nodes.map(n=>n.getAttribute('fill'))")
    page.evaluate("() => { document.querySelector('#align-tracks').checked=true; document.querySelector('#orient-tracks').checked=true; state.trackDirections.set(1,-1); render(); }")
    assert page.locator('.feature').evaluate_all("nodes=>nodes.map(n=>n.getAttribute('fill'))") == colors
    assert page.evaluate("state.features.filter(f=>f.type==='CDS').map(replicationClass)") == ['co-oriented', 'head-on']
    assert not errors
    page.close()
