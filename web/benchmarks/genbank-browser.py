"""Compare GenBank parsing in fresh browser contexts, including long ORIGIN lines."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', required=True)
parser.add_argument('--baseline-dir', type=Path, required=True)
parser.add_argument('--candidate-dir', type=Path, default=Path('web/mauve_web/static/browser'))
args = parser.parse_args()
sources = {label: {name: (root / name).read_text() for name in ['core.mjs', 'genbank.mjs']}
           for label, root in [('baseline', args.baseline_dir), ('candidate', args.candidate_dir)]}
report = {'runs': [], 'bases': 5000000, 'features': 10000,
          'source_sha256': {label: {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()} for label, files in sources.items()}}
expected = None
with sync_playwright() as p:
    executable = os.environ.get('MAUVE_CHROME_PATH')
    chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    if not executable and chrome.exists():
        executable = str(chrome)
    browser = p.chromium.launch(**({'executable_path': executable} if executable else {}))
    report['browser'] = browser.version
    for repeat in range(3):
        for label in (['baseline', 'candidate'] if repeat % 2 == 0 else ['candidate', 'baseline']):
            context = browser.new_context()
            context.route(args.url, lambda route: route.fulfill(body='<!doctype html><title>GenBank benchmark</title>', content_type='text/html'))
            context.route('**/static/browser/*.mjs', lambda route: route.fulfill(
                body=sources[label][route.request.url.rsplit('/', 1)[-1]], content_type='text/javascript'))
            page = context.new_page()
            page.goto(args.url)
            cases = page.evaluate('''async () => {
              const {parseRecords} = await import('./static/browser/genbank.mjs');
              const bases = 5000000, sequence = 'acgtn'.repeat(bases / 5), encoder = new TextEncoder();
              const features = Array.from({length: 10000}, (_, i) => `     gene            ${i * 100 + 1}..${i * 100 + 50}\\n                     /gene="gene-${i}"\\n                     /note="test β annotation"`).join('\\n');
              const digest = async bytes => [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(b => b.toString(16).padStart(2, '0')).join('');
              const cases = [];
              for (const width of [60, 0]) {
                const origin = width ? Array.from({length: Math.ceil(bases / width)}, (_, i) => String(i * width + 1).padStart(9) + ' ' + sequence.slice(i * width, (i + 1) * width)).join('\\n') : '        1 ' + sequence;
                const blob = new Blob([`LOCUS       synthetic ${bases} bp\\nFEATURES             Location/Qualifiers\\n${features}\\nORIGIN\\n${origin}\\n//\\n`]);
                await parseRecords(blob);
                const start = performance.now();
                const records = await parseRecords(blob);
                const ms = performance.now() - start;
                if (records.length !== 1 || records[0].sequence.length !== bases || records[0].features.length !== 10000) throw Error('Unexpected parsed records');
                const {sequence: bytes, ...metadata} = records[0];
                cases.push({width, ms, input_bytes: blob.size, sequence_sha256: await digest(bytes), metadata_sha256: await digest(encoder.encode(JSON.stringify(metadata)))});
              }
              return cases;
            }''')
            for case in cases:
                signature = (case['sequence_sha256'], case['metadata_sha256'])
                if expected is not None and signature != expected:
                    raise RuntimeError('GenBank sequences or annotations changed')
                expected = signature
                report['runs'].append({'label': label, 'repeat': repeat, **case})
            context.close()
    browser.close()
report['medians_ms'] = {width: {label: statistics.median(r['ms'] for r in report['runs'] if r['label'] == label and r['width'] == width) for label in sources} for width in [60, 0]}
report['outputs_identical'] = True
print(json.dumps(report, indent=2))
