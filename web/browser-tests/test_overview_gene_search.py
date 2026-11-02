"""Gene-search interactions with the map and inspector, in both execution modes.

Run from the repository root:
  PYTHONPATH=web web/.venv/bin/python -m pytest web/browser-tests/test_overview_gene_search.py -q
"""
from io import StringIO
import xml.etree.ElementTree as ET

import pytest
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation, CompoundLocation
from Bio.SeqRecord import SeqRecord
from test_gene_analysis import analysis_site, site, browser, browser_app


def gene(name, start, end, strand=1, **qualifiers):
    return SeqFeature(SimpleLocation(start - 1, end, strand=strand), type='CDS',
                      qualifiers={'gene': [name], **{k: [v] for k, v in qualifiers.items()}})


def import_genes(page, gid, features):
    record = SeqRecord(Seq('ACGT' * 500), id='chr', name='chr',
                       annotations={'molecule_type': 'DNA', 'topology': 'circular'})
    record.features = features
    output = StringIO()
    SeqIO.write(record, output, 'genbank')
    page.locator('#annotation-genome').select_option(str(gid))
    page.locator('#annotation-file').set_input_files({
        'name': f'genome{gid}.gbk', 'mimeType': 'text/plain', 'buffer': output.getvalue().encode()})
    page.wait_for_function("document.querySelector('#notice').textContent.startsWith('Imported ')")
    page.wait_for_function("!document.querySelector('#import-annotations').disabled")


@pytest.fixture
def gene_page(analysis_site, browser):
    mode, url = analysis_site
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url)
    if mode == 'static':
        page.wait_for_function('window.mauveReady === true')
    dna = 'ACGT' * 50
    xmfa = f'> 1:101-300 + first.fa\n{dna}\n> 2:1101-1300 - second.fa\n{dna}\n=\n'
    xmfa += f'> 1:501-700 + first.fa\n{dna}\n> 2:1501-1700 + second.fa\n{dna}\n=\n'
    xmfa += f'> 1:901-1100 + first.fa\n{dna}\n=\n'
    page.locator('#file').set_input_files({'name': 'search-context.xmfa', 'mimeType': 'text/plain', 'buffer': xmfa.encode()})
    page.wait_for_function('state.alignment?.genomes.length === 2')
    import_genes(page, 1, [
        gene('match_alpha', 150, 170, locus_tag='LOC_A', product='DNA repair enzyme'),
        gene('match_beta', 550, 570, locus_tag='LOC_B'),
        gene('match_singleton', 950, 970), gene('outside', 350, 370),
        SeqFeature(CompoundLocation([SimpleLocation(49, 60, strand=1), SimpleLocation(349, 360, strand=1)]),
                   type='CDS', qualifiers={'gene': ['compound_gap']}),
        SeqFeature(CompoundLocation([SimpleLocation(1979, 2000, strand=1), SimpleLocation(0, 20, strand=1)]),
                   type='CDS', qualifiers={'gene': ['origin_gene']}),
    ])
    import_genes(page, 2, [gene('match_alpha', 1231, 1251, -1, locus_tag='LOC_C', product='DNA repair enzyme'),
                           gene('match_beta', 1550, 1570, locus_tag='LOC_D')])
    page.locator('#reset').click()
    yield page
    assert not errors
    page.close()


def search(page, query):
    page.locator('#overview-gene-query').fill(query)
    page.locator('#overview-gene-search button').first.click()
    page.wait_for_function("!document.querySelector('#overview-gene-status').textContent.match(/Searching|Finding gene/)")


def select_block(page, bid):
    page.evaluate('(bid) => selectBlock(bid)', bid)
    page.wait_for_function('(bid) => state.selected === bid && state.profile !== null', arg=bid)
    page.wait_for_function("!document.querySelector('#feature-limit').textContent.startsWith('Loading')")


def context(page):
    return page.evaluate('''() => ({range: [state.start, state.end], selected: state.selected,
      offset: state.offset, reference: state.reference, directions: [...state.trackDirections],
      offsets: [...state.trackOffsets], order: state.order, detail: state.detail,
      filters: ['min-columns', 'isolate-block', 'shared-only', 'core-genes-only', 'show-annotations',
                'show-identity', 'links'].map(id => [id, $(id).type === 'checkbox' ? $(id).checked : $(id).value])})''')


def markers(page):
    return page.locator('.gene-search-marker')


@pytest.mark.parametrize('control,value', [
    ('min-columns', '500'), ('isolate-block', True), ('shared-only', True),
    ('show-annotations', False), ('show-identity', False), ('links', False),
])
def test_search_preserves_block_filters_and_inspector(gene_page, control, value):
    page = gene_page
    select_block(page, 2)
    page.locator('#display-settings summary').click()
    if isinstance(value, bool):
        page.locator(f'#{control}').set_checked(value)
    else:
        page.locator(f'#{control}').fill(value)
        page.locator(f'#{control}').dispatch_event('input')
    before = context(page)
    search(page, 'match_')
    assert markers(page).count() == 5
    assert context(page) == before
    page.locator('#overview-gene-results button').first.click()
    assert context(page) == before
    assert page.locator('.gene-search-marker[aria-pressed="true"]').count() == 1
    page.locator('#overview-gene-clear').click()
    assert markers(page).count() == 0
    assert context(page) == before


def test_search_with_real_core_families_and_explicit_focus(gene_page):
    page = gene_page
    page.locator('#run-gene-analysis').click()
    page.wait_for_function('window.mauveGeneAnalysis?.result !== null && window.mauveGeneAnalysis?.result !== undefined')
    select_block(page, 1)
    page.locator('#display-settings summary').click()
    page.locator('#core-genes-only').check()
    assert page.evaluate('coreBlockIds.has(1) && !coreBlockIds.has(3)')
    before = context(page)
    search(page, 'match_singleton')
    assert markers(page).count() == 1
    page.locator('#overview-gene-results button').first.click()
    assert context(page) == before
    assert page.locator('rect.block[data-block-id="3"]').count() == 0
    page.locator('#overview-gene-focus').click()
    page.wait_for_function('state.selected === 3')
    assert not page.locator('#core-genes-only').is_checked()
    assert page.evaluate('visibleBlocks().some(b => b.id === 3)')
    assert page.evaluate('state.start <= 950 && state.end >= 970')


def test_block_clicks_paging_zoom_and_fit_keep_search(gene_page):
    page = gene_page
    select_block(page, 1)
    search(page, 'match_')
    page.locator('rect.block[aria-label^="Block 2, sequence 1,"]').click(position={'x': 5, 'y': 5})
    page.wait_for_function('state.selected === 2')
    assert len(page.evaluate('state.overviewMatches')) == 5
    page.locator('#next').click()
    page.wait_for_function('state.offset === 100')
    assert page.locator('#columns').inner_text() == '101–200'
    page.locator('#zoom-in').click()
    page.locator('#pan-right').click()
    assert len(page.evaluate('state.overviewMatches')) == 5
    page.locator('#reset').click()
    assert markers(page).count() == 5
    page.locator('#zoom-selected').click()
    assert page.evaluate('state.selected') == 2
    assert len(page.evaluate('state.overviewMatches')) == 5
    page.locator('#block-search').fill('1')
    page.locator('#block-list button').first.click()
    page.wait_for_function('state.selected === 1')
    page.locator('#reset').click()
    assert markers(page).count() == 5
    page.wait_for_selector('.conservation-profile')
    assert page.locator('.conservation-profile').count() > 0
    assert page.locator('.page-window').count() > 0


def test_track_visibility_order_reference_and_orientation(gene_page):
    page = gene_page
    select_block(page, 1)
    search(page, 'match_alpha')
    page.locator('#display-settings summary').click()
    page.locator('#align-tracks').check()
    page.locator('#orient-tracks').check()
    page.wait_for_function('state.trackDirections.get(2) === -1')
    # Corresponding genes on the inverted member project to the same location.
    xs = markers(page).evaluate_all("nodes => nodes.map(node => Number(node.getAttribute('x')))")
    assert len(xs) == 2 and abs(xs[0] - xs[1]) < 0.01
    before = context(page)
    search(page, 'LOC_C')
    page.locator('#overview-gene-results button').click()
    assert context(page) == before
    page.locator('#reference-genome').select_option('2')
    page.wait_for_function('state.reference === 2 && state.profile?.reference_id === 2')
    assert markers(page).count() == 1
    page.locator('.track-settings summary').click()
    page.locator('.track-control[data-genome="2"] button').first.click()
    assert page.evaluate('state.order') == [2, 1]
    page.locator('.track-control[data-genome="2"] input').uncheck()
    assert markers(page).count() == 0
    search(page, 'LOC_C')
    assert markers(page).count() == 1
    assert page.evaluate('state.order') == [2, 1]
    page.locator('#reset-display').click()
    assert markers(page).count() == 1
    assert page.evaluate('state.trackDirections.size === 0 && state.trackOffsets.size === 0')


@pytest.mark.parametrize('query,count', [('outside', 1), ('compound_gap', 2), ('origin_gene', 2)])
def test_unaligned_and_compound_genes_do_not_select_false_blocks(gene_page, query, count):
    page = gene_page
    select_block(page, 2)
    before = context(page)
    search(page, query)
    assert markers(page).count() == count
    page.locator('#overview-gene-results button').click()
    assert context(page) == before
    assert 'Outside aligned blocks' in page.locator('#overview-gene-status').inner_text()
    page.locator('#overview-gene-focus').click()
    assert page.evaluate('state.selected') == 2
    assert 'Outside aligned blocks' in page.locator('#overview-gene-status').inner_text()


def test_circular_wrap_clipping_and_marker_keyboard(gene_page):
    page = gene_page
    search(page, 'origin_gene')
    page.locator('#display-settings summary').click()
    page.locator('#align-tracks').check()
    page.evaluate('setRange(1950, 2050, false)')
    assert markers(page).count() == 2
    rects = markers(page).evaluate_all("nodes => nodes.map(node => ({x: +node.getAttribute('x'), width: +node.getAttribute('width')}))")
    rects.sort(key=lambda rect: rect['x'])
    assert abs(rects[0]['x'] + rects[0]['width'] - rects[1]['x']) < 0.01  # Adjacent across the origin.
    before = context(page)
    markers(page).first.focus()
    page.keyboard.press('Enter')
    assert context(page) == before
    assert page.locator('.gene-search-marker[aria-pressed="true"]').count() == 2
    page.evaluate('setRange(600, 800, false)')
    assert markers(page).count() == 0
    assert len(page.evaluate('state.overviewMatches')) == 1
    page.locator('#reset').click()
    assert markers(page).count() == 2


def test_results_keyboard_mobile_and_export(gene_page, tmp_path):
    page = gene_page
    search(page, 'DNA REPAIR')
    assert markers(page).count() == 2
    results = page.locator('#overview-gene-results button')
    results.first.focus()
    page.keyboard.press('ArrowDown')
    assert results.nth(1).evaluate('e => e === document.activeElement')
    page.keyboard.press('Enter')
    assert results.nth(1).get_attribute('aria-pressed') == 'true'
    page.keyboard.press('Escape')
    assert page.locator('#overview-gene-query').evaluate('e => e === document.activeElement')
    page.locator('.export-menu summary').click()
    with page.expect_download() as download:
        page.locator('#export-svg').click()
    path = tmp_path / 'gene-search.svg'
    download.value.save_as(path)
    svg = ET.parse(path).getroot()
    exported = [node for node in svg.iter() if node.attrib.get('class') == 'gene-search-marker']
    assert len(exported) == 2
    assert all('var(' not in node.attrib.get('style', '') for node in exported)
    assert all('tabindex' not in node.attrib for node in exported)
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    search(page, 'LOC_A')
    assert markers(page).count() == 1


def test_annotation_reimport_and_alignment_switch_reset_search(gene_page):
    page = gene_page
    search(page, 'match_alpha')
    page.locator('#overview-gene-results button').first.click()
    import_genes(page, 1, [gene('replacement', 150, 170)])
    assert markers(page).count() == 0
    assert page.locator('#overview-gene-results button').count() == 0
    assert page.locator('#overview-gene-focus').is_disabled()
    search(page, 'match_alpha')
    assert markers(page).count() == 1
    assert markers(page).get_attribute('data-genome') == '2'
    aid = page.evaluate('state.alignment.id')
    xmfa = '> 1:1-4 + new.fa\nACGT\n> 2:1-4 + other.fa\nACGT\n=\n'
    page.locator('#file').set_input_files({'name': 'new.xmfa', 'mimeType': 'text/plain', 'buffer': xmfa.encode()})
    page.wait_for_function('(aid) => state.alignment.id !== aid', arg=aid)
    assert markers(page).count() == 0
    assert page.locator('#overview-gene-query').input_value() == ''
    assert 'Import GenBank' in page.locator('#overview-gene-status').inner_text()
    search(page, 'match')
    assert 'Import GenBank' in page.locator('#overview-gene-status').inner_text()
    assert page.locator('#overview-gene-focus').is_disabled()


# Controlled API gates reproduce races without sleeps or depending on machine speed.
def gate_api(page, substring):
    page.evaluate('''substring => {
      const original = api;
      window.gateEntered = false;
      window.gateFinished = false;
      const gate = new Promise(resolve => { window.releaseGate = resolve; });
      api = async (...args) => {
        const result = await original(...args);
        if (args[0].includes(substring)) {
          window.gateEntered = true;
          await gate;
          window.gateFinished = true;
          if (window.gateError) throw Error(window.gateError);
        }
        return result;
      };
      window.restoreApi = () => { api = original; };
    }''', substring)


@pytest.mark.parametrize('action', ['clear', 'new_query', 'switch_alignment'])
def test_stale_search_cannot_restore_old_highlights(gene_page, action):
    page = gene_page
    aid = page.evaluate('state.alignment.id')
    gate_api(page, '/features?q=match_alpha')
    page.locator('#overview-gene-query').fill('match_alpha')
    page.locator('#overview-gene-search button').first.click()
    page.wait_for_function('window.gateEntered')
    if action == 'clear':
        page.locator('#overview-gene-clear').click()
    elif action == 'new_query':
        search(page, 'LOC_B')
    else:
        # Reopening also changes the alignment epoch even when the ID is unchanged.
        page.evaluate('(aid) => openAlignment(aid)', aid)
    page.evaluate('releaseGate()')
    page.wait_for_function('window.gateFinished')
    page.evaluate('restoreApi()')
    assert markers(page).count() == (1 if action == 'new_query' else 0)
    assert page.locator('#overview-gene-results button').count() == (1 if action == 'new_query' else 0)
    if action == 'new_query':
        assert 'LOC_B' in page.locator('#overview-gene-results').inner_text()


def test_search_failure_and_retry_preserve_block_context(gene_page):
    page = gene_page
    select_block(page, 2)
    before = context(page)
    page.evaluate('''() => {
      const original = api;
      window.restoreApi = () => { api = original; };
      api = (...args) => args[0].includes('/features?q=') ? Promise.reject(Error('Injected search failure')) : original(...args);
    }''')
    search(page, 'match_alpha')
    assert 'Injected search failure' in page.locator('#overview-gene-status').inner_text()
    assert markers(page).count() == 0
    assert context(page) == before
    page.evaluate('restoreApi()')
    search(page, 'match_alpha')
    assert markers(page).count() == 2
    assert context(page) == before


def test_new_block_selection_wins_over_pending_gene_zoom(gene_page):
    page = gene_page
    search(page, 'LOC_A')
    page.locator('#overview-gene-results button').click()
    gate_api(page, '/blocks/1?')
    page.locator('#overview-gene-focus').click()
    page.wait_for_function('window.gateEntered')
    select_block(page, 2)
    before = context(page)
    page.evaluate('releaseGate()')
    page.wait_for_function('window.gateFinished')
    page.evaluate('restoreApi()')
    assert context(page) == before
    assert 'Selected block 1' not in page.locator('#overview-gene-status').inner_text()


def test_search_reveals_matching_track_in_sequence_inspector(gene_page):
    page = gene_page
    select_block(page, 1)
    page.locator('.track-settings summary').click()
    page.locator('.track-control[data-genome="2"] input').uncheck()
    assert page.locator('.sequence-row[data-genome="2"]').count() == 0
    before = context(page)
    search(page, 'LOC_C')
    assert markers(page).count() == 1
    assert page.locator('.sequence-row[data-genome="2"]').count() == 1
    assert context(page) == before


@pytest.mark.parametrize('action', ['clear', 'new_match'])
def test_changed_search_selection_cancels_pending_gene_zoom(gene_page, action):
    page = gene_page
    select_block(page, 2)
    search(page, 'match_')
    page.locator('#overview-gene-results button').first.click()
    gate_api(page, '/blocks/1?')
    page.locator('#overview-gene-focus').click()
    page.wait_for_function('window.gateEntered')
    if action == 'clear':
        page.locator('#overview-gene-clear').click()
    else:
        page.locator('#overview-gene-results button').nth(1).click()
    before = context(page)
    page.evaluate('releaseGate()')
    page.wait_for_function('window.gateFinished')
    page.evaluate('restoreApi()')
    assert context(page) == before


@pytest.mark.parametrize('action', ['clear', 'reimport', 'failure'])
def test_second_search_page_is_atomic_and_cancellable(gene_page, action):
    page = gene_page
    import_genes(page, 1, [gene(f'page_hit_{index}', 150, 170) for index in range(505)])
    gate_api(page, '/features?q=page_hit&limit=500&offset=500')
    page.locator('#overview-gene-query').fill('page_hit')
    page.locator('#overview-gene-search button').first.click()
    page.wait_for_function('window.gateEntered')
    # A partial response must not look like a complete search on the map.
    assert markers(page).count() == 0
    if action == 'clear':
        page.locator('#overview-gene-clear').click()
    elif action == 'reimport':
        import_genes(page, 1, [gene('new_annotation', 150, 170)])
    else:
        page.evaluate("window.gateError = 'Second page unavailable'")
    page.evaluate('releaseGate()')
    page.wait_for_function('window.gateFinished')
    page.evaluate('restoreApi()')
    assert markers(page).count() == 0
    assert page.locator('#overview-gene-results button').count() == 0
    if action == 'failure':
        assert 'Second page unavailable' in page.locator('#overview-gene-status').inner_text()
        search(page, 'page_hit')
        assert markers(page).count() == 505
        assert page.locator('#overview-gene-results button').count() == 51
    elif action == 'reimport':
        search(page, 'new_annotation')
        assert markers(page).count() == 1


def test_duplicate_loci_and_literal_labels(gene_page):
    page = gene_page
    label = '<b>match & gene</b>'
    cds = gene(label, 150, 170, locus_tag='LOC_LITERAL', product='<img src=x onerror=alert(1)>')
    locus = gene(label, 150, 170, locus_tag='LOC_LITERAL')
    locus.type = 'gene'
    import_genes(page, 1, [cds, locus])
    search(page, 'LOC_LITERAL')
    assert markers(page).count() == 2
    assert page.locator('#overview-gene-results button').count() == 2
    assert page.locator('#overview-gene-results img, #overview-gene-results b').count() == 0
    assert label in page.locator('#overview-gene-results').inner_text()
    page.locator('#overview-gene-results button').first.click()
    assert page.locator('#feature-detail img, #feature-detail b').count() == 0
    assert label in page.locator('#feature-detail').inner_text()
    assert page.locator('.gene-search-marker[aria-pressed="true"]').count() == 1
    page.locator('#overview-gene-results button').nth(1).click()
    assert page.locator('.gene-search-marker[aria-pressed="true"]').count() == 1
    search(page, 'no-such-gene')
    assert markers(page).count() == 0
    assert 'No matching' in page.locator('#overview-gene-status').inner_text()
    search(page, '   ')
    assert 'Enter a gene' in page.locator('#overview-gene-status').inner_text()
