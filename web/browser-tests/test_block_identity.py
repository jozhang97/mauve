"""Highlighted-block identity is visible on the map and follows its reference."""
from test_gene_analysis import analysis_site, site, browser, browser_app


def test_highlighted_block_identity_labels_and_svg(analysis_site, browser, tmp_path):
    mode, url = analysis_site
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url)
    if mode == 'static':
        page.wait_for_function('window.mauveReady === true')
    alignment = '''> 1:1-7 + reference.fa
ACGT-NAA
> 2:1-7 - target.fa
ACCTTN-A
> 3:1-8 + ambiguous.fa
NNNNNNNN
=
> 2:8-11 + target.fa
AAAA
> 4:1-4 + absent.fa
AAAA
=
> 1:8-11 + reference.fa
AAAA
> 2:12-15 + target.fa
AAAA
=
'''
    page.locator('#file').set_input_files({'name': 'identity.xmfa', 'mimeType': 'text/plain', 'buffer': alignment.encode()})
    page.wait_for_function('state.alignment?.genomes.length === 4')
    assert page.locator('.block-identity').count() == 0
    page.locator('svg .block').first.click()
    page.wait_for_function('state.profile?.reference_id === 1')
    label = lambda gid: page.locator(f'.block-identity[data-genome="{gid}"] .block-identity-value')
    assert label(1).text_content() == 'Reference'
    assert label(2).text_content() == '80.00% block identity'
    assert label(3).text_content() == 'N/A · no comparable bases'
    assert label(4).text_content() == 'Absent from block'
    assert 'Block 1 · 5 pairs' in page.locator('.block-identity[data-genome="2"] .tick').text_content()
    assert '4 matches / 5 comparable' in page.locator('.block-identity[data-genome="2"] title').text_content()
    assert page.locator('svg .block title').filter(has_text='80.00% block identity').count() == 1
    assert 'Whole-block nucleotide identity vs reference.fa' in page.locator('#identity-status').inner_text()
    # Zoom does not change the full-block denominator.
    page.locator('#region').fill('1-3'); page.locator('#region-form button').click()
    assert label(2).text_content() == '80.00% block identity'
    page.locator('.export-menu summary').click()
    with page.expect_download() as download:
        page.locator('#export-svg').click()
    download.value.save_as(tmp_path / 'identity.svg')
    exported = (tmp_path / 'identity.svg').read_text()
    assert '80.00% block identity' in exported and 'Block 1 · 5 pairs' in exported
    page.locator('.export-menu summary').click()
    page.locator('#reset').click()
    page.locator('#overview-panel').screenshot(path=str(tmp_path / 'block-identity.png'))
    page.locator('#reference-genome').select_option('2')
    page.wait_for_function('state.profile?.reference_id === 2')
    assert label(1).text_content() == '80.00% block identity'
    assert label(2).text_content() == 'Reference'
    page.locator('#reference-genome').select_option('4')
    page.wait_for_function('state.profile?.reference_id === 4')
    assert label(1).text_content() == 'N/A · reference absent'
    assert label(4).text_content() == 'Absent from block'
    page.locator('#reference-genome').select_option('1')
    page.evaluate('selectBlock(3)')
    page.wait_for_function('state.profile?.reference_id === 1 && state.selected === 3 && state.profile.members[0]?.matches === 4')
    assert label(2).text_content() == '100.00% block identity'
    assert 'Block 3 · 4 pairs' in page.locator('.block-identity[data-genome="2"] .tick').text_content()
    page.locator('#display-settings summary').click()
    page.locator('#show-identity').uncheck()
    assert page.locator('.block-identity').count() == 0
    page.locator('#show-identity').check()
    page.wait_for_function('state.profile?.members[0]?.matches === 4')
    assert label(2).text_content() == '100.00% block identity'
    page.locator('#min-columns').fill('999')
    assert page.locator('.block-identity').count() == 0
    assert not errors
    page.close()
