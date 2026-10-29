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
    assert {p.name for p in output.iterdir()} == {'index.html', '.nojekyll', 'static'}
    html = (output / 'index.html').read_text()
    assert 'src="/static/' not in html
    assert 'href="/"' not in html
    assert 'Closing the browser does not stop a job' not in html
    assert 'browser/client.js' in html
    assert not (output / 'static/index.html').exists()
    assert not list(output.rglob('*.sqlite3'))
    assert not list(output.rglob('*.fa'))
    assert (output / 'static/wasm/build.py').is_file()
    manifest = json.loads((output / 'static/wasm/SOURCES.json').read_text())
    assert hashlib.sha256((output / 'static/wasm/progressiveMauve.wasm').read_bytes()).hexdigest() == manifest['wasm_sha256']
