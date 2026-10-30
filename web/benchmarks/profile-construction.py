"""Compare CPU identity profile construction in fresh browser contexts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', required=True)
parser.add_argument('--baseline-core', type=Path, required=True)
parser.add_argument('--candidate-core', type=Path, default=Path('web/mauve_web/static/browser/core.mjs'))
args = parser.parse_args()
sources = {'baseline': args.baseline_core.read_text(), 'candidate': args.candidate_core.read_text()}
report = {'source_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in sources.items()}, 'runs': [], 'columns': 1000000, 'bins': 200, 'timing': 'mean of 20 complete CPU profiles after five warmups; three alternating fresh contexts per engine'}
expected = {}
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
            context.route(args.url, lambda route: route.fulfill(body='<!doctype html><title>Profile benchmark</title>', content_type='text/html'))
            context.route('**/core.mjs', lambda route: route.fulfill(body=sources[label], content_type='text/javascript'))
            page = context.new_page()
            page.goto(args.url)
            cases = page.evaluate('''async () => {
              const {pairCounts, indexMember, profileMember} = await import('./core.mjs');
              let seed = 12345;
              const random = () => {seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed >>> 8;};
              const cases = [];
              for (const kind of ['same', 'mixed', 'gaps', 'ambiguous']) {
                const alphabet = new TextEncoder().encode(kind === 'ambiguous' ? 'ACGTNRYSWKMBDHV' : kind === 'gaps' ? 'ACGT----' : 'ACGT');
                const a = new Uint8Array(1000000), b = new Uint8Array(a.length);
                for (let i = 0; i < a.length; i++) {a[i] = alphabet[random() % alphabet.length]; b[i] = kind === 'same' ? a[i] : alphabet[random() % alphabet.length];}
                const member = indexMember({genome_id: 2, start: 1, end: a.reduce((n, x) => n + (x !== 45), 0), strand: '-', sequence: a});
                const run = () => profileMember(member, a.length, 5000, pairCounts(a, b, 5000));
                for (let i = 0; i < 5; i++) run();
                const start = performance.now();
                let output;
                for (let i = 0; i < 20; i++) output = run();
                cases.push({kind, ms: (performance.now() - start) / 20, output});
              }
              return cases;
            }''')
            for case in cases:
                output = case.pop('output')
                if case['kind'] in expected and expected[case['kind']] != output:
                    raise RuntimeError('Identity profile changed')
                expected[case['kind']] = output
                report['runs'].append({'repeat': repeat, 'label': label, **case})
            context.close()
    browser.close()
report['medians_ms'] = {kind: {label: statistics.median(r['ms'] for r in report['runs'] if r['label'] == label and r['kind'] == kind) for label in sources} for kind in expected}
report['outputs_identical'] = True
print(json.dumps(report, indent=2))
