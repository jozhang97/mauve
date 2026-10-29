"""Optional end-to-end checks; see README for browser setup."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import httpx
import pytest

pytestmark = pytest.mark.skipif(os.environ.get('MAUVE_BROWSER_TESTS') != '1', reason='Set MAUVE_BROWSER_TESTS=1 to run browser checks')
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def browser_app(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'MAUVE_DATA_DIR': str(tmp_path / 'data')}
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'mauve_web.app:create_app', '--factory', '--port', str(port)],
                               cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    url = f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            if process.poll() is not None:
                pytest.fail(process.stderr.read().decode())
            try:
                if httpx.get(url, timeout=1).status_code == 200:
                    break
            except httpx.ConnectError:
                pass
            time.sleep(.05)
        else:
            pytest.fail('Server did not start.')
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_annotations_exports_and_existing_viewer(browser_app, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        executable = os.environ.get('MAUVE_CHROME_PATH')
        browser = p.chromium.launch(**({'executable_path': executable} if executable else {}))
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(browser_app)
            page.locator('#welcome-demo').click()
            page.wait_for_selector('svg .feature')
            assert page.locator('#genome-count').inner_text() == '2'
            assert '2,000 canonical aligned bases' in page.locator('#annotation-status').inner_text()
            page.locator('#gene-query').fill('TEL01L-TR')
            page.locator('#feature-search button').click()
            page.locator('#feature-results button').first.click()
            assert 'TEL01L-TR' in page.locator('#feature-detail').inner_text()
            assert '1–62 (-)' in page.locator('#feature-detail').inner_text()
            assert page.locator('#range').inner_text() != '1–2,000 bp'
            page.locator('#reset').click()
            page.locator('#block-list button').first.click()
            page.wait_for_selector('.base-row')
            page.locator('#next').click()
            page.wait_for_function("document.querySelector('#columns').textContent === '101–200'")
            page.locator('#zoom-in').click()
            page.locator('#region').fill('100-800')
            page.locator('#region-form button').click()
            assert page.locator('#range').inner_text() == '100–800 bp'
            page.locator('#reset').click()
            page.wait_for_selector('svg .feature')
            page.screenshot(path=str(tmp_path / 'desktop.png'), full_page=True)
            page.locator('.export-menu summary').click()
            for control, filename in [('#export-svg', 'view.svg'), ('#export-fasta', 'block.fasta'), ('#export-blocks', 'blocks.tsv')]:
                with page.expect_download() as info:
                    page.locator(control).click()
                info.value.save_as(tmp_path / filename)
            svg = ET.parse(tmp_path / 'view.svg').getroot()
            assert svg.tag.endswith('svg')
            assert svg.attrib['width']
            assert 'TEL01L' in (tmp_path / 'view.svg').read_text()
            assert '>sequence_1' in (tmp_path / 'block.fasta').read_text()
            assert 'start_1based' in (tmp_path / 'blocks.tsv').read_text()
            # Reimport the correct annotation file; failed multi-record imports preserve it.
            page.locator('#annotation-file').set_input_files(str(ROOT / 'demo.gbk'))
            page.wait_for_selector('#notice.error')
            assert 'multiple records' in page.locator('#notice').inner_text()
            page.locator('#concatenate-records').check()
            page.locator('#annotation-file').set_input_files(str(ROOT / 'demo.gbk'))
            page.wait_for_function("document.querySelector('#notice').textContent.startsWith('Imported ')")
            # Wrong genome fails sequence verification rather than silently misplacing genes.
            page.locator('#annotation-genome').select_option('1')
            page.locator('#annotation-file').set_input_files(str(ROOT / 'demo.gbk'))
            page.wait_for_selector('#notice.error')
            assert 'does not match' in page.locator('#notice').inner_text()
            page.reload()
            page.wait_for_selector('svg .feature')
            page.locator('#display-settings summary').click()
            page.locator('#show-annotations').uncheck()
            assert page.locator('svg .feature').count() == 0
            page.locator('#show-annotations').check()
            assert page.locator('svg .feature').count() > 0
            page.set_viewport_size({'width': 390, 'height': 844})
            page.screenshot(path=str(tmp_path / 'mobile.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert not errors, errors
        finally:
            browser.close()


@pytest.mark.skipif(os.environ.get('MAUVE_NATIVE_TESTS') != '1', reason='Requires a native progressiveMauve executable')
def test_native_alignment_workflow(browser_app, tmp_path):
    import random
    playwright = pytest.importorskip('playwright.sync_api')
    rng = random.Random(23)
    sequence = ''.join(rng.choices('ACGT', k=5000))
    with playwright.sync_playwright() as p:
        executable = os.environ.get('MAUVE_CHROME_PATH')
        browser = p.chromium.launch(**({'executable_path': executable} if executable else {}))
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(browser_app)
            page.locator('#new-alignment').click()
            page.wait_for_function("document.querySelector('#engine-status').textContent.startsWith('Ready')")
            page.locator('#job-name').fill('Browser alignment test')
            page.locator('#sequence-files').set_input_files([
                {'name': name, 'mimeType': 'text/plain', 'buffer': f'>genome\n{sequence}\n'.encode()}
                for name in ('first.fasta','second.fasta')])
            page.wait_for_function("document.querySelectorAll('#staged-inputs li').length === 2 && !document.querySelector('#submit-job').disabled")
            page.screenshot(path=str(tmp_path / 'alignment-form.png'), full_page=True)
            page.locator('#submit-job').click()
            page.wait_for_function("document.querySelector('#job-status').textContent === 'succeeded'", timeout=60000)
            assert page.locator('#open-result').is_visible()
            assert page.locator('#rerun-job').is_visible()
            assert page.locator('#job-library button').count() == 1
            assert page.locator('#job-log').inner_text()
            with page.expect_download() as info:
                page.locator('#job-artifacts a').filter(has_text='Parameters').click()
            info.value.save_as(tmp_path / 'manifest.json')
            import json
            manifest = json.loads((tmp_path / 'manifest.json').read_text())
            assert [i['name'] for i in manifest['inputs']] == ['first.fasta','second.fasta']
            page.screenshot(path=str(tmp_path / 'completed-job.png'), full_page=True)
            page.locator('#open-result').click()
            page.wait_for_selector('svg .block')
            assert page.locator('#title').inner_text() == 'Browser alignment test'
            assert page.locator('#genome-count').inner_text() == '2'
            page.reload()
            page.wait_for_selector('#job-library button')
            page.locator('#job-library button').first.click()
            page.wait_for_function("document.querySelector('#job-status').textContent === 'succeeded'")
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert not errors, errors
        finally:
            browser.close()


def test_theme_preference_and_svg_export(browser_app, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        executable = os.environ.get('MAUVE_CHROME_PATH')
        browser = p.chromium.launch(**({'executable_path': executable} if executable else {}))
        page = browser.new_page(viewport={'width':1440,'height':1100}, color_scheme='dark')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(browser_app)
            assert page.locator('html').get_attribute('data-theme') == 'dark'
            page.locator('#welcome-demo').click()
            page.wait_for_selector('svg .feature')
            page.locator('#block-list button').first.click()
            page.wait_for_selector('.base-row')
            assert page.locator('.panel').first.evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgb(30, 33, 43)'
            assert page.locator('.genome-name').first.evaluate('e=>getComputedStyle(e).fill') == 'rgb(210, 215, 228)'
            page.screenshot(path=str(tmp_path/'dark-viewer.png'), full_page=True)
            with page.expect_download() as info:
                page.locator('.export-menu summary').click()
                page.locator('#export-svg').click()
            info.value.save_as(tmp_path/'dark.svg')
            root = ET.parse(tmp_path/'dark.svg').getroot()
            background = root.find('{http://www.w3.org/2000/svg}rect')
            assert background.attrib['fill'] == '#1e212b'
            page.locator('#theme').select_option('light')
            assert page.locator('html').get_attribute('data-theme') == 'light'
            page.reload()
            assert page.locator('html').get_attribute('data-theme') == 'light'
            page.locator('#theme').select_option('dark')
            page.emulate_media(color_scheme='light')
            assert page.locator('html').get_attribute('data-theme') == 'dark'
            page.locator('#new-alignment').click()
            assert page.locator('#alignment-dialog').evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgb(30, 33, 43)'
            page.locator('#close-alignment-dialog').click()
            page.locator('#theme').select_option('system')
            assert page.locator('html').get_attribute('data-theme') == 'light'
            page.emulate_media(color_scheme='dark')
            page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
            page.set_viewport_size({'width':390,'height':844})
            assert page.locator('#theme').is_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert not errors, errors
        finally:
            browser.close()


def test_ncbi_selection_across_pages_and_alignment_form(browser_app, tmp_path):
    import random
    from urllib.parse import parse_qs, urlparse
    playwright=pytest.importorskip('playwright.sync_api')
    rng=random.Random(18)
    sequence=''.join(rng.choices('ACGT',k=5000))
    with playwright.sync_playwright() as p:
        executable=os.environ.get('MAUVE_CHROME_PATH')
        browser=p.chromium.launch(**({'executable_path':executable} if executable else {}))
        page=browser.new_page(viewport={'width':1440,'height':1100},color_scheme='dark')
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        def row(index):
            acc=f'GCF_{index:09d}.1'
            return {'accession':acc,'url':f'https://www.ncbi.nlm.nih.gov/datasets/genome/{acc}/','source':'RefSeq','name':f'Assembly {index}',
                    'organism':'Test organism','strain':f'Strain {index}','taxon_id':2097,'level':'Complete Genome','status':'current',
                    'release_date':'2020-01-01','bases':5000,'contigs':1,'paired_accession':f'GCA_{index:09d}.1'}
        def search(route):
            params=parse_qs(urlparse(route.request.url).query)
            assert params['taxon_id']==['2097']
            next_page=params.get('page_token')==['second']
            route.fulfill(json={'taxon':{'id':2097,'name':'Test organism','rank':'species'},'assemblies':[row(26)] if next_page else [row(i) for i in range(1,26)],
                                'total':26,'next_page_token':'' if next_page else 'second','includes_descendants':True})
        downloads=[]
        def download(route):
            acc=urlparse(route.request.url).path.split('/')[-2]
            downloads.append(acc)
            if acc=='GCF_000000026.1' and downloads.count(acc)==1:
                route.fulfill(status=502,json={'detail':'Temporary NCBI download error'})
                return
            response=route.fetch(url=browser_app+'/api/inputs?name='+acc+'.fna',method='POST',post_data=f'>genome\n{sequence}\n',headers={'Content-Type':'application/octet-stream'})
            route.fulfill(response=response)
        page.route('**/api/ncbi/assemblies?*',search)
        page.route('**/api/ncbi/assemblies/*/input',download)
        try:
            page.goto(browser_app)
            page.locator('#browse-ncbi').click()
            page.locator('#ncbi-taxon').fill('2097')
            page.locator('#ncbi-search-button').click()
            page.wait_for_selector('#ncbi-results tr')
            page.get_by_role('checkbox',name='Select GCF_000000001.1',exact=True).check()
            page.locator('#ncbi-next').click()
            page.get_by_role('checkbox',name='Select GCF_000000026.1',exact=True).check()
            assert '2 selected' in page.locator('#ncbi-selection-count').inner_text()
            page.locator('#ncbi-previous').click()
            assert page.get_by_role('checkbox',name='Select GCF_000000001.1',exact=True).is_checked()
            page.screenshot(path=str(tmp_path/'ncbi-dark.png'),full_page=True)
            page.locator('#ncbi-use').click()
            page.wait_for_selector('#ncbi-error:not([hidden])')
            assert page.locator('#staged-inputs li').count()==1
            assert '1 selected' in page.locator('#ncbi-selection-count').inner_text()
            page.locator('#ncbi-use').click()
            page.wait_for_selector('#alignment-dialog[open]')
            page.wait_for_function("!document.querySelector('#submit-job').disabled")
            assert downloads.count('GCF_000000001.1')==1
            assert downloads.count('GCF_000000026.1')==2
            assert page.locator('#staged-inputs li').count()==2
            assert 'GCF_000000026.1' in page.locator('#staged-inputs').inner_text()
            assert page.locator('#job-name').input_value()=='Taxon 2097 alignment'
            if os.environ.get('MAUVE_NATIVE_TESTS')=='1':
                page.locator('#submit-job').click()
                page.wait_for_function("document.querySelector('#job-status').textContent==='succeeded'",timeout=60000)
                page.locator('#open-result').click()
                page.wait_for_selector('svg .block')
                assert page.locator('#genome-count').inner_text()=='2'
            else:
                page.locator('#close-alignment-dialog').click()
            page.set_viewport_size({'width':390,'height':844})
            page.locator('#browse-ncbi').click()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert not errors,errors
        finally:
            browser.close()


def test_richer_viewer(browser_app, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        executable = os.environ.get('MAUVE_CHROME_PATH')
        browser = p.chromium.launch(**({'executable_path': executable} if executable else {}))
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        try:
            page.goto(browser_app)
            page.locator('#welcome-demo').click()
            page.wait_for_selector('svg .feature')
            page.locator('#block-list button').first.click()
            page.wait_for_selector('.identity-window')
            assert 'Only A/C/G/T pairs count' in page.locator('#identity-status').inner_text()
            assert not page.locator('#differences-only').is_checked()
            assert page.locator('.sequence-row .base').count() == 200
            assert 'identity' in page.locator('.row-identity').last.inner_text()
            page.locator('.sequence-row .base').first.click()
            assert 'Column 1' in page.locator('#column-detail').inner_text()
            page.locator('.sequence-row .base').first.press('ArrowRight')
            assert 'Column 2' in page.locator('#column-detail').inner_text()
            assert page.locator('.active-column').count() == 2
            page.locator('#comparison-summary summary').click()
            assert 'Base substitutions' in page.locator('#comparison-summary').inner_text()
            page.locator('#comparison-summary summary').click()
            page.locator('#differences-only').check()
            assert page.locator('.sequence-row .base:not(.diff)').count() == 0
            page.locator('#differences-only').uncheck()
            assert page.locator('.sequence-row .base').count() == 200
            page.locator('#column-detail button').first.click()
            assert page.locator('#range').inner_text() != '1–2,000 bp'
            page.locator('#reset').click()
            page.locator('#next-difference').click()
            page.wait_for_function("!document.querySelector('#difference-status').textContent.includes('Finding')")

            page.locator('#reference-genome').select_option('2')
            page.wait_for_function("state.profile?.reference_id === 2")
            page.locator('#focus-reference').click()
            assert page.locator('#range').inner_text() != '1–2,000 bp'
            page.locator('#reset').click()
            page.locator('.track-settings summary').click()
            page.locator('[data-genome="2"] button').first.click()
            assert 'cerevisiae' in page.locator('svg .genome-name').first.text_content()
            page.locator('[data-genome="2"] input').uncheck()
            assert page.locator('svg .genome-name').count() == 1
            assert page.locator('svg .feature').count() == 0
            assert page.locator('[data-genome="1"] input').is_disabled()
            assert 'NaN' not in page.locator('#tracks').inner_html()
            page.locator('[data-genome="2"] input').check()
            page.locator('#display-settings summary').click()
            page.locator('#isolate-block').check()
            assert page.locator('#block-list button').count() == 1
            page.locator('#min-columns').fill('999999')
            assert page.locator('svg .block').count() == 0
            assert page.locator('.identity-window').count() == 0
            page.locator('#min-columns').fill('0')
            page.locator('#show-identity').uncheck()
            assert page.locator('.identity-window').count() == 0
            page.locator('#show-identity').check()
            page.wait_for_selector('.identity-window')
            page.locator('#block-search').fill('does-not-exist')
            assert 'No matching blocks' in page.locator('#block-list').inner_text()
            page.locator('#reset-display').click()
            assert page.locator('#block-list button').count() == 5
            assert page.locator('#block-search').input_value() == ''
            page.locator('#block-search').fill('2')
            assert page.locator('#block-list button').count() == 1
            page.locator('#block-search').fill('')
            page.locator('#jump-sequence').click()
            assert page.evaluate("document.activeElement.id") == 'sequence-panel'
            page.locator('[data-section="overview-panel"]').click()
            assert page.evaluate("document.activeElement.id") == 'overview-panel'
            page.locator('#display-settings summary').click()
            page.locator('.track-settings summary').click()
            page.locator('#theme').select_option('dark')
            page.wait_for_timeout(200)
            page.screenshot(path=str(tmp_path / 'richer-viewer.png'), full_page=True)
            page.locator('.inspector').screenshot(path=str(tmp_path / 'sequence-comparison.png'))
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert not errors, errors
        finally:
            browser.close()


def test_review_fixes_linked_navigation_filters_and_mobile(browser_app, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    # A gap in genome 1 and a reverse member ensure positions cannot be
    # approximated by subtracting block starts.
    text = ('> 1:1-1000 + first.fa\n' + 'A' * 500 + '-' + 'A' * 500
            + '\n> 2:101-1101 - second.fa\n' + 'A' * 1001
            + '\n> 3:201-1201 + third.fa\n' + 'A' * 1001 + '\n=')
    aid = httpx.post(browser_app + '/api/alignments?name=Linked%20navigation', content=text).json()['id']
    other = httpx.post(browser_app + '/api/alignments?name=Other%20alignment', content=text).json()['id']
    with playwright.sync_playwright() as p:
        executable = os.environ.get('MAUVE_CHROME_PATH')
        browser = p.chromium.launch(**({'executable_path': executable} if executable else {}))
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        try:
            page.goto(browser_app + '/#' + aid)
            page.locator('#block-list button').click()
            page.wait_for_selector('.sequence-row')
            page.locator('#region').fill('600-650')
            page.locator('#region-form button').click()
            page.wait_for_function('state.offset === 600')
            assert page.evaluate('state.detail.members[0].positions[0]') == 600
            page.locator('#jump-sequence').click()
            assert page.locator('#columns').inner_text() == '601–700'
            assert page.locator('.page-window').count() == 3
            page.locator('#sequence-location-kind').select_option('genomic')
            page.locator('#sequence-genome').select_option('2')
            page.locator('#sequence-position').fill('650')
            # A still-running older backend ignores the new query parameters.
            # Refuse that response rather than silently displaying a wrong base.
            def old_backend(route):
                from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
                parts = urlsplit(route.request.url)
                query = [(k, v) for k, v in parse_qsl(parts.query) if k not in ('genome_id', 'position')]
                response = route.fetch(url=urlunsplit(parts._replace(query=urlencode(query))))
                route.fulfill(response=response)
            page.route('**/blocks/1?*', old_backend)
            page.locator('#sequence-jump button').click()
            page.wait_for_selector('#notice.error')
            assert 'server restart' in page.locator('#notice').inner_text()
            assert page.evaluate('state.offset') == 600
            page.unroute('**/blocks/1?*', old_backend)
            page.locator('#sequence-jump button').click()
            page.wait_for_function('state.offset === 451')
            assert page.evaluate('state.detail.members[1].positions[0]') == 650
            assert page.evaluate('state.start <= 650 && state.end >= 650')
            page.locator('#sequence-location-kind').select_option('column')
            page.locator('#sequence-position').fill('800')
            page.locator('#sequence-jump button').click()
            page.wait_for_function('state.offset === 799')
            page.locator('.track-settings summary').click()
            page.locator('[data-genome="3"] button').first.click()
            assert page.locator('.sequence-row').evaluate_all('(rows) => rows.map(r => r.dataset.genome)') == ['1', '3', '2']
            page.locator('[data-genome="2"] input').uncheck()
            assert page.locator('.sequence-row').evaluate_all('(rows) => rows.map(r => r.dataset.genome)') == ['1', '3']
            assert 'second.fa' not in page.locator('#column-detail').inner_text()
            page.locator('#display-settings summary').click()
            page.locator('#min-columns').fill('2000')
            assert page.locator('#map-feedback').is_visible()
            assert 'hidden by filters' in page.locator('#selection-feedback').inner_text()
            assert 'hidden on map' in page.locator('#selection-status').inner_text()
            page.locator('#reveal-selected').click()
            assert page.locator('#selection-feedback').is_hidden()
            assert page.locator('.sequence-row').count() == 3
            page.locator('[data-section="sequence-panel"]').click()
            page.wait_for_function('window.scrollY > 100')
            page.locator('#library button', has_text='Other alignment').click()
            page.wait_for_function('state.alignment.id === ' + repr(other))
            page.wait_for_function('window.scrollY === 0')
            assert page.locator('#sequence-navigation').is_hidden()
            mobile = browser.new_page(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
            mobile.on('pageerror', lambda e: errors.append(str(e)))
            mobile.goto(browser_app + '/#' + aid)
            mobile.locator('#block-list button').click()
            mobile.wait_for_selector('.sequence-row')
            assert mobile.locator('#columns').inner_text() == '1–25'
            assert mobile.locator('.sequence-row .base').count() == 75
            assert mobile.locator('#sequence-scroll-hint').is_visible()
            assert mobile.locator('.sequence-row .base-label').first.bounding_box()['width'] == 64
            mobile.locator('#full-sequence-labels').check()
            assert mobile.locator('.sequence-row .base-label').first.bounding_box()['width'] == 160
            mobile.locator('#full-sequence-labels').uncheck()
            mobile.locator('#page-size').select_option('50')
            mobile.wait_for_function('state.detail.members[0].bases.length === 50')
            assert mobile.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            mobile.locator('[data-section="sequence-panel"]').click()
            mobile.screenshot(path=str(tmp_path / 'linked-mobile.png'))
            mobile.close()
            assert not errors, errors
        finally:
            browser.close()
