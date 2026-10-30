"""Compare forward/reverse annotation verification in fresh browser contexts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', required=True)
parser.add_argument('--baseline-genbank', type=Path, required=True)
parser.add_argument('--candidate-genbank', type=Path, default=Path('web/mauve_web/static/browser/genbank.mjs'))
args = parser.parse_args()
current = Path('web/mauve_web/static/browser')
sources = {'baseline': args.baseline_genbank.read_text(), 'candidate': args.candidate_genbank.read_text()}
core = (current / 'core.mjs').read_text()
report = {'runs': [], 'genome_bases': 1000000, 'source_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in sources.items()}}
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
            context.route(args.url, lambda route: route.fulfill(body='<!doctype html><title>Verification benchmark</title>', content_type='text/html'))
            context.route('**/static/browser/genbank.mjs', lambda route: route.fulfill(body=sources[label], content_type='text/javascript'))
            context.route('**/static/browser/core.mjs', lambda route: route.fulfill(body=core, content_type='text/javascript'))
            page = context.new_page()
            page.goto(args.url)
            cases = page.evaluate('''async () => {
              const {verifyMember} = await import('./static/browser/genbank.mjs');
              const complement = {65: 84, 84: 65, 67: 71, 71: 67}, cases = [];
              for (const kind of ['forward', 'reverse', 'reverse-mixed-gaps']) {
                const pattern = kind.endsWith('gaps') ? 'ACGTNRYSWKMBDHV' : 'ACGT';
                const genome = new TextEncoder().encode(pattern.repeat(Math.ceil(1000000 / pattern.length)).slice(0, 1000000));
                const bases = kind === 'forward' ? genome : genome.slice().reverse().map(x => complement[x] || x);
                let sequence = bases;
                if (kind.endsWith('gaps')) {
                  sequence = new Uint8Array(bases.length + Math.floor(bases.length / 31));
                  let offset = 0;
                  for (let i = 0; i < bases.length; i++) {sequence[offset++] = bases[i]; if (i % 31 === 30) sequence[offset++] = 45;}
                }
                const member = {start: 1, end: genome.length, strand: kind === 'forward' ? '+' : '-', sequence};
                const expected = genome.reduce((n, x) => n + Number([65, 67, 71, 84].includes(x)), 0);
                for (let i = 0; i < 5; i++) if (verifyMember(member, genome) !== expected) throw Error('Verification count changed');
                const start = performance.now();
                let actual;
                for (let i = 0; i < 5; i++) actual = verifyMember(member, genome);
                const ms = (performance.now() - start) / 5;
                if (actual !== expected) throw Error('Verification count changed');
                cases.push({kind, ms, verified_bases: actual, alignment_columns: sequence.length});
              }
              return cases;
            }''')
            report['runs'].extend({'label': label, 'repeat': repeat, **case} for case in cases)
            context.close()
    browser.close()
report['medians_ms'] = {kind: {label: statistics.median(r['ms'] for r in report['runs'] if r['label'] == label and r['kind'] == kind) for label in sources} for kind in ['forward', 'reverse', 'reverse-mixed-gaps']}
print(json.dumps(report, indent=2))
