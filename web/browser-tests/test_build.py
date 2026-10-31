import importlib.util
import json
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_pages', ROOT / 'build_pages.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


def test_pages_artifact_is_static_and_engine_matches_manifest(tmp_path):
    output = tmp_path / 'site'
    builder.build(output)
    assert {p.name for p in output.iterdir()} == {'index.html', '.nojekyll', 'static', 'isolation-sw.js'}
    html = (output / 'index.html').read_text()
    assert 'src="/static/' not in html
    assert 'href="/"' not in html
    assert 'Closing the browser does not stop a job' not in html
    assert 'browser/client.js' in html
    assert not (output / 'static/index.html').exists()
    assert not list(output.rglob('*.sqlite3'))
    assert not list(output.rglob('*.fa'))
    demo = output / 'static/demo/ecoli'
    manifest = json.loads((demo / 'manifest.json').read_text())
    assert len(manifest['genomes']) == 8
    assert (demo / manifest['alignment']['file']).is_file()
    assert all((demo / g['annotations']).is_file() for g in manifest['genomes'])
    assert not (output / 'static/demo.alignment').exists()
    assert 'Open E. coli demo' in html and 'Explore 8 E. coli strains' in html
    assert (output / 'static/wasm/build.py').is_file()
    for engine in ('wasm', 'wasm-threaded'):
        folder = output / 'static' / engine
        manifest = json.loads((folder / 'SOURCES.json').read_text())
        assert manifest['configuration']['threaded'] == (engine == 'wasm-threaded')
        assert hashlib.sha256((folder / 'progressiveMauve.wasm').read_bytes()).hexdigest() == manifest['wasm_sha256']
        for name, digest in manifest['local_sources'].items():
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest



def test_analytics_configuration_is_explicit_and_validated(tmp_path):
    import pytest
    output = tmp_path / 'tracked'
    builder.build(output, 'jozhang97')
    assert '"siteCode": "jozhang97"' in (output / 'static/analytics-config.js').read_text()
    html = (output / 'index.html').read_text()
    assert html.index('analytics-config.js') < html.index('analytics.js') < html.index('browser/client.js')
    assert 'Usage analytics count visits and actions.' in html
    local = tmp_path / 'local'
    builder.build(local)
    assert '"siteCode": ""' in (local / 'static/analytics-config.js').read_text()
    for code in ['https://example.org', 'bad code', '<script>']:
        with pytest.raises(ValueError):
            builder.build(tmp_path / 'invalid', code)
    assert not (tmp_path / 'invalid').exists()
