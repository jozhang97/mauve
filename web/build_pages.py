"""Build the standalone browser app, without Python APIs or user data."""
import argparse
import json
import os
import re
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent

def build(output, goatcounter_code=''):
    goatcounter_code = goatcounter_code.strip()
    if goatcounter_code and not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', goatcounter_code):
        raise ValueError('Use a GoatCounter site code, not a URL or API key.')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'mauve_web/static'
    for name in ('progressiveMauve.mjs', 'progressiveMauve.wasm'):
        if not (source / 'wasm' / name).is_file():
            raise RuntimeError('Build the WebAssembly engine first: see wasm/README.md')
    shutil.copytree(source, output / 'static', ignore=shutil.ignore_patterns('index.html'))
    shutil.copyfile(ROOT / 'wasm/build.py', output / 'static/wasm/build.py')
    shutil.copytree(ROOT / 'wasm/optimizations', output / 'static/wasm/optimizations')
    (output / 'static/analytics-config.js').write_text(
        'window.MAUVE_ANALYTICS = ' + json.dumps({'siteCode': goatcounter_code}) + ';\n')
    # The entrypoint is at the project root, so every resource respects /repo/.
    html = (source / 'index.html').read_text().replace(
        '    <script src="./static/app.js"',
        '    <script src="./static/analytics-config.js"></script>\n'
        '    <script src="./static/analytics.js"></script>\n'
        '    <script src="./static/browser/client.js"></script>\n    <script src="./static/app.js"')
    html = html.replace('<div class="sidebar-footer">', '<div class="sidebar-footer"><p id="compute-status">Starting local compute…</p><p id="local-status">Files stay in this browser</p>')
    if goatcounter_code:
        html = html.replace('<p id="local-status">Files stay in this browser</p>', '<p id="local-status">Files stay in this browser</p><p>Usage analytics count visits and actions. Genome data, filenames, and search queries are excluded.</p>')
    html = html.replace('2–8', '2–64').replace('up to 8 assemblies', 'up to 64 assemblies')
    html = html.replace('id="alignment-form">', 'id="alignment-form"><p class="small">Runs on this device. Keep this tab open until the job finishes. Saved results belong to this browser; export important work. Larger genome counts are experimental.</p>')
    html = html.replace('workspace. Closing the browser does not stop a job.', 'browser. Closing this tab interrupts unfinished jobs; saved results remain available.')
    (output / 'index.html').write_text(html)
    for name in ('demo.alignment', 'demo.gbk'):
        shutil.copyfile(ROOT / name, output / 'static' / name)
    (output / '.nojekyll').touch()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--goatcounter-code', default=os.environ.get('MAUVE_GOATCOUNTER_CODE', ''))
    args = parser.parse_args()
    build(args.output, args.goatcounter_code)
