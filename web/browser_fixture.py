"""Small legacy alignment for fast viewer tests, independent of the public demo."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def open_small_fixture(page):
    page.locator('#file').set_input_files(str(ROOT / 'demo.alignment'))
    page.wait_for_function('state.alignment?.genomes.length === 2')
    page.locator('#annotation-genome').select_option('2')
    page.locator('#concatenate-records').check()
    page.locator('#annotation-file').set_input_files(str(ROOT / 'demo.gbk'))
    page.wait_for_function('state.sources.length === 1')
    page.locator('#concatenate-records').uncheck()
    page.evaluate('selectBlock(1)')
    page.wait_for_function('state.features.length > 0')
