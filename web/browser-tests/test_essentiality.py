"""Essentiality evidence through annotation import, gene worker, filters and export."""
import json
from io import StringIO
from pathlib import Path
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord
from test_gene_analysis import analysis_site, browser_app
from test_browser import site, browser


def test_essentiality_import_filter_and_export(analysis_site, browser):
    mode, url = analysis_site
    fixtures = json.loads((Path(__file__).resolve().parents[1] / 'data/essentiality/test-cds.json').read_text())
    sequence = ''.join(f['sequence'] for f in fixtures) + 'ACGT' * 15
    context = browser.new_context(service_workers='block')
    # Model a browser cache that still serves pre-essentiality worker/modules
    # at their old unversioned URLs. Updated entrypoints must bypass them.
    stale_requests = []
    versioned_requests = []
    def old_cache(route):
        from urllib.parse import urlparse, parse_qs
        version = parse_qs(urlparse(route.request.url).query).get('v')
        if version:
            versioned_requests.append((urlparse(route.request.url).path, version[0]))
            route.continue_()
        else:
            stale_requests.append(route.request.url)
            route.fulfill(content_type='text/javascript', body='throw new Error("Stale pre-essentiality code");')
    context.route('**/browser/gene-worker.mjs*', old_cache)
    context.route('**/browser/gene-analysis.mjs*', old_cache)

    page = context.new_page()
    page.goto(url)
    if mode == 'static':
        page.wait_for_function('window.mauveReady === true')
    xmfa = ''.join(f'> {gid}:1-{len(sequence)} + genome{gid}.fa\n{sequence}\n' for gid in [1, 2]) + '=\n'
    page.locator('#file').set_input_files({'name':'essentiality.xmfa', 'mimeType':'text/plain', 'buffer':xmfa.encode()})
    page.wait_for_function('state.alignment?.genomes.length === 2')
    for gid in [1, 2]:
        record = SeqRecord(Seq(sequence), id='chr', name='chr', annotations={'molecule_type':'DNA', 'topology':'circular'})
        record.features = [SeqFeature(SimpleLocation(0, 1), type='rep_origin')]
        at = 0
        for f in fixtures + [{'name':'unknown', 'sequence':'ACGT' * 15}]:
            end = at + len(f['sequence'])
            record.features.append(SeqFeature(SimpleLocation(at, end, strand=1), type='CDS', qualifiers={'gene':[f['name']], 'locus_tag':[f'LOC_{at}']}))
            at = end
        output = StringIO(); SeqIO.write(record, output, 'genbank')
        page.locator('#annotation-genome').select_option(str(gid))
        page.locator('#annotation-file').set_input_files({'name':f'{gid}.gbk', 'mimeType':'text/plain', 'buffer':output.getvalue().encode()})
        page.wait_for_function(f'state.sources.length === {gid}')
    page.locator('#run-gene-analysis').click()
    page.wait_for_function('window.mauveGeneAnalysis.result?.families.length === 3')
    assert '1 with essential reference evidence; 2 with any reference evidence' in page.locator('#gene-essentiality-status').inner_text()
    for status, name in [('essential', 'rplL'), ('nonessential', 'thrL'), ('unknown', 'unknown')]:
        page.locator('#gene-essentiality-filter').select_option(status)
        assert page.locator('#gene-family-table tbody tr').count() == 1
        assert name in page.locator('#gene-family-table').inner_text()
        assert f'({status} reference evidence)' in page.locator('#gene-family-page').inner_text()
        assert 'Current filters: 1 families' in page.locator('#gene-essentiality-status').inner_text()
    page.locator('#gene-family-core').check()
    assert page.locator('#gene-family-table tbody tr').count() == 1
    with page.expect_download() as event:
        page.locator('#export-gene-families').click()
    exported = Path(event.value.path()).read_text()
    assert 'reference_essentiality' in exported
    assert 'identical CDS sequence; strain essentiality not established' in exported
    assert 'https://doi.org/10.1128/mBio.02096-17' in exported
    result = page.evaluate('window.mauveGeneAnalysis.result')
    assert result['essentiality_source']['reference'] == 'CP009273.1'
    assert not stale_requests
    assert len(versioned_requests) >= 2
    assert len({version for _, version in versioned_requests}) == 1
    assert sum(m['essentiality']['status'] == 'essential' for f in result['families'] for m in f['members']) == 2
    assert page.locator('#gene-pan-summary [data-essentiality="essential"] strong').all_text_contents() == ['1', '1', '0']
    assert page.locator('#gene-genome-counts tbody tr').first.locator('td').all_text_contents()[-2:] == ['1', '1']
    assert '1 essential reference matches' in page.locator('#gene-occupancy').inner_text()
    page.evaluate('selectBlock(1)')
    page.wait_for_function('state.features.length === 8')
    page.evaluate('showFeature(state.features.find(f=>f.name === "rplL"))')
    assert 'Reference essentiality: essential' in page.locator('#feature-detail').inner_text()
    page.evaluate('setRange(1,state.max,false)')
    page.locator('#display-settings summary').click()
    page.locator('#show-replication').check()
    fills = page.locator('.feature[data-essential-reference="true"]').evaluate_all('nodes=>nodes.map(n=>n.getAttribute("fill"))')
    assert len(fills) == 2
    page.locator('#highlight-essential').check()
    assert page.locator('.feature[data-essential-reference="true"]').evaluate_all('nodes=>nodes.every(n=>n.getAttribute("stroke")==="#8b4fba")')
    assert page.locator('.feature[data-essential-reference="true"]').evaluate_all('nodes=>nodes.map(n=>n.getAttribute("fill"))') == fills
    page.locator('#essential-genes-only').check()
    assert page.locator('.feature').count() == 2
    assert page.locator('.feature[data-essential-reference="true"]').count() == 2
    page.locator('#core-genes-only').check()
    assert page.locator('.feature').count() == 2
    assert 'in core families' in page.locator('#essential-genes-status').inner_text()
    assert page.evaluate('visibleBlocks().length') == 1
    page.locator('#essential-genes-only').uncheck()
    page.locator('#core-genes-only').uncheck()
    assert page.locator('.feature').count() == 8
    page.locator('#highlight-essential').uncheck()
    page.wait_for_function('window.mauveOriginAnalysis?.result?.ranges.length === 3')
    assert page.locator('#origin-fractions tbody tr').last.locator('td').all_text_contents()[:2] == ['essential reference matches', '2']
    def series_total(target, series):
        return page.locator(f'#{target} rect[data-series="{series}"]').evaluate_all('nodes=>nodes.reduce((n,b)=>n+Number(b.dataset.value),0)')
    assert series_total('origin-distances', 'essential reference matches') == 2
    assert page.locator('#origin-distances .histogram-legend [data-legend-series]').count() == 3
    assert 'essential reference matches (n=2)' in page.locator('#origin-distances .histogram-legend').text_content()
    assert page.locator('#origin-ranges .histogram-legend [data-legend-series]').count() == 2
    assert 'Essential-core families (n=1)' in page.locator('#origin-ranges .histogram-legend').text_content()
    assert page.locator('.histogram-key i').count() == 2
    page.locator('#origin-range-scale').select_option('percent')
    for metric in ['position', 'distance']:
        page.locator('#origin-range-metric').select_option(metric)
        assert series_total('origin-ranges', 'Core families') == 100
        assert series_total('origin-ranges', 'Essential-core families') == 100
        assert page.locator('#origin-ranges svg').get_attribute('aria-label').endswith('percent within each gene set')
        assert 'Core families (n=3)' in page.locator('#origin-ranges .histogram-legend').text_content()
        assert 'Essential-core families (n=1)' in page.locator('#origin-ranges .histogram-legend').text_content()
    page.locator('#origin-range-scale').select_option('count')
    assert series_total('origin-ranges', 'Core families') == 3
    page.locator('#origin-range-metric').select_option('position')

    assert series_total('origin-ranges', 'Essential-core families') == 1
    page.locator('#origin-range-metric').select_option('distance')
    assert series_total('origin-ranges', 'Essential-core families') == 1
    page.locator('#origin-range-metric').select_option('position')
    assert page.locator('#origin-range-table tbody tr').filter(has_text='rplL').locator('td').nth(2).inner_text() == 'essential'
    page.locator('#origin-histogram-scale').select_option('percent')
    assert series_total('origin-distances', 'essential reference matches') == 100
    page.locator('#origin-genome').select_option('1')
    page.locator('#origin-histogram-scale').select_option('count')
    assert series_total('origin-distances', 'essential reference matches') == 1
    assert series_total('origin-ranges', 'Essential-core families') == 1
    context.route('**/essentiality-ecoli.json', lambda route: route.fulfill(status=503, body='unavailable'))
    page.locator('#run-gene-analysis').click()
    page.wait_for_function('window.mauveGeneAnalysis.result?.essentiality_error')
    assert page.locator('#gene-essentiality-filter').input_value() == 'unknown'
    assert page.locator('#gene-family-core').is_checked()
    assert 'Essentiality unavailable' in page.locator('#gene-essentiality-status').inner_text()
    assert 'HTTP 503' in page.locator('#gene-essentiality-error').inner_text()
    assert page.locator('#gene-pan-summary [data-essentiality=essential] strong').all_text_contents() == ['N/A', 'N/A', 'N/A']
    assert page.locator('#gene-family-table tbody tr').count() == 3
    context.close()
