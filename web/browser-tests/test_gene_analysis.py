"""End-to-end all-pairs analysis through the static browser worker and UI."""
import json
import importlib.util
from io import StringIO
from pathlib import Path
import pytest
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord
from test_browser import site, browser

spec = importlib.util.spec_from_file_location('gene_backend_fixture', Path(__file__).resolve().parents[1] / 'tests/test_browser.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
browser_app = backend.browser_app


@pytest.fixture(params=['static', 'server'])
def analysis_site(request):
    return request.param, request.getfixturevalue('site' if request.param == 'static' else 'browser_app')


def test_all_pairs_core_pan_and_exports(analysis_site, browser, tmp_path):
    mode, site = analysis_site
    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(site)
    if mode == 'static':
        page.wait_for_function('window.mauveReady === true')
    sequences = ['A' * 40, 'A' * 10 + '-' * 10 + 'A' * 20, 'A' * 10 + 'T' * 10 + 'A' * 20]
    xmfa = ''.join(f'> {i}:1-{len(s.replace("-", ""))} + genome{i}.fa\n{s}\n' for i, s in enumerate(sequences, 1)) + '=\n'
    page.locator('#file').set_input_files({'name': 'circular.xmfa', 'mimeType': 'text/plain', 'buffer': xmfa.encode()})
    page.wait_for_function('state.alignment?.genomes.length === 3')
    page.locator('#run-gene-analysis').click()
    page.wait_for_function('document.querySelector("#gene-analysis-status").textContent.includes("Import GenBank")')
    for gid, aligned in enumerate(sequences, 1):
        sequence = aligned.replace('-', '')
        record = SeqRecord(Seq(sequence), id='chr', name='chr', annotations={'molecule_type': 'DNA', 'topology': 'circular'})
        record.features = [SeqFeature(SimpleLocation(start, start + 10, strand=1), type='CDS', qualifiers={'locus_tag': [f'gene{start//10}']}) for start in range(0, len(sequence), 10)]
        output = StringIO(); SeqIO.write(record, output, 'genbank')
        page.locator('#annotation-genome').select_option(str(gid))
        page.locator('#annotation-file').set_input_files({'name': f'genome{gid}.gbk', 'mimeType': 'text/plain', 'buffer': output.getvalue().encode()})
        page.wait_for_function(f'state.sources.length === {gid}')
    page.locator('#run-gene-analysis').click()
    page.wait_for_function('document.querySelector("#gene-analysis-status").textContent.startsWith("Computed 3 pairs")')
    assert page.locator('#gene-heatmap tbody tr').count() == 3
    assert page.locator('#gene-pan-summary strong').all_text_contents() == ['5', '3', '3', '2', '2', '0']
    assert page.locator('#gene-family-table tbody tr').count() == 5
    page.locator('#gene-metric').select_option('dcj')
    assert page.locator('#gene-heatmap tbody tr').first.locator('td').all_text_contents() == ['—', '0', '0']
    for control, filename in [('#export-gene-pairs', 'pairs.tsv'), ('#export-gene-families', 'families.tsv'), ('#export-gene-json', 'analysis.json')]:
        with page.expect_download() as event: page.locator(control).click()
        event.value.save_as(tmp_path / filename)
    result = json.loads((tmp_path / 'analysis.json').read_text())
    assert result['pairs'][0]['adjacency_jaccard'] == .4
    assert result['pairs'][0]['content_jaccard'] == .75
    assert result['pairs'][0]['conservation'] == 1
    assert result['occupancy'] == [2, 0, 3]
    assert len((tmp_path / 'pairs.tsv').read_text().splitlines()) == 4
    assert len((tmp_path / 'families.tsv').read_text().splitlines()) == 12
    page.locator('#gene-family-search').fill('F1')
    assert page.locator('#gene-family-table tbody tr').count() == 1
    page.locator('#gene-family-search').fill('')
    page.locator('#gene-analysis-panel').screenshot(path=str(tmp_path / 'gene-analysis.png'))
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.locator('#gene-rna').select_option('experimental')
    assert page.locator('#gene-analysis-results').is_hidden()
    page.evaluate('document.querySelector("#run-gene-analysis").click(); document.querySelector("#cancel-gene-analysis").click()')
    assert page.locator('#gene-analysis-status').inner_text() == 'Analysis canceled.'
    page.locator('#run-gene-analysis').click()
    page.wait_for_function('document.querySelector("#gene-analysis-status").textContent.startsWith("Computed 3 pairs")')
    assert not errors
    page.close()
