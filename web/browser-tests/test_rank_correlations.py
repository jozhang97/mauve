"""Oriented circular core ranks use complete chromosomes and a shared anchor."""
from io import StringIO
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord
from test_gene_analysis import analysis_site, site, browser, browser_app


def test_core_rank_correlations(analysis_site, browser, tmp_path):
    mode, url = analysis_site
    page = browser.new_page(viewport={'width':1440,'height':1100})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(url)
    if mode=='static': page.wait_for_function('window.mauveReady === true')
    xmfa='> 1:101-200 + first.fa\n'+'A'*100+'\n> 2:1101-1200 - second.fa\n'+'A'*100+'\n=\n'
    page.locator('#file').set_input_files({'name':'ranks.xmfa','mimeType':'text/plain','buffer':xmfa.encode()})
    page.wait_for_function('state.blocks.length === 1')
    for gid,base,starts,strand in [(1,'A',[120,150,180],1),(2,'T',[1171,1141,1111],-1)]:
        record=SeqRecord(Seq(base*2000),id='chr',name='chr',annotations={'molecule_type':'DNA','topology':'circular'})
        record.features=[SeqFeature(SimpleLocation(start-1,start+10,strand=strand),type='CDS',qualifiers={'locus_tag':[f'g{i}']}) for i,start in enumerate(starts)]
        out=StringIO();SeqIO.write(record,out,'genbank')
        page.locator('#annotation-genome').select_option(str(gid))
        page.locator('#annotation-file').set_input_files({'name':f'g{gid}.gbk','mimeType':'text/plain','buffer':out.getvalue().encode()})
        page.wait_for_function(f'state.sources.length === {gid}')
    page.evaluate('selectBlock(1)')
    page.locator('#display-settings summary').click()
    page.locator('#core-genes-only').check()
    page.wait_for_function('window.mauveGeneAnalysis?.result')
    page.locator('#gene-metric').select_option('kendall')
    assert 'Enable' in page.locator('#core-rank-status').inner_text()
    assert page.locator('#gene-heatmap tbody tr').first.locator('td').all_text_contents() == ['—', 'N/A']
    page.locator('#orient-tracks').check()
    page.wait_for_function('window.mauveRankCorrelations?.result?.pairs.length === 1')
    pair=page.evaluate('window.mauveRankCorrelations.result.pairs[0]')
    assert (pair['n'],pair['kendall'],pair['spearman']) == (3,1,1)
    for metric in ['kendall', 'spearman']:
        page.locator('#gene-metric').select_option(metric)
        assert page.locator('#gene-heatmap tbody tr').first.locator('td').all_text_contents() == ['—', '1.0000']
        assert page.locator('#gene-heatmap tbody tr').nth(1).locator('td').all_text_contents() == ['1.0000', '—']
        assert '−1 to +1' in page.locator('#gene-heatmap-legend').inner_text()
    assert page.locator('#overview-panel #core-rank-panel').count() == 0
    assert page.locator('#gene-analysis-panel #core-rank-status').is_visible()

    assert page.evaluate('window.mauveRankCorrelations.result.directions[2]') == -1
    page.locator('#zoom-selected').click()
    page.evaluate('setRange(-400,1599,false)')
    assert page.evaluate('window.mauveRankCorrelations.result.pairs[0]') == pair
    page.locator('#reference-genome').select_option('2')
    page.wait_for_function('window.mauveRankCorrelations.result.directions[1] === -1')
    assert page.evaluate('window.mauveRankCorrelations.result.pairs[0].kendall') == 1
    with page.expect_download() as event: page.locator('#export-core-ranks').click()
    event.value.save_as(tmp_path/'ranks.tsv')
    assert len((tmp_path/'ranks.tsv').read_text().splitlines()) == 2
    page.locator('#orient-tracks').uncheck()
    assert page.evaluate('window.mauveRankCorrelations.result') is None
    assert page.locator('#gene-heatmap tbody tr').first.locator('td').all_text_contents() == ['—', 'N/A']
    assert page.locator('#export-core-ranks').is_hidden()
    page.locator('#gene-metric').select_option('dcj')
    assert page.locator('#core-rank-status').is_hidden()
    assert not errors, errors
    page.close()
