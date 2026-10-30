"""Compare track-control rendering and checkbox/order state in fresh browsers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', required=True)
parser.add_argument('--baseline-app', type=Path, required=True)
parser.add_argument('--genomes', type=int, action='append')
parser.add_argument('--visibility', choices=['all', 'half', 'one'], action='append')
parser.add_argument('--repeats', type=int, default=3)
parser.add_argument('--iterations', type=int, default=5)
args = parser.parse_args()
genome_counts = args.genomes or [8, 64, 128]
visibilities = args.visibility or ['all', 'half', 'one']
if min(*genome_counts, args.repeats, args.iterations) < 1:
    parser.error('Counts must be positive')
sources = {'baseline': args.baseline_app.read_text(), 'candidate': Path('web/mauve_web/static/app.js').read_text()}
report = {'runs': [], 'genomes': genome_counts, 'visibilities': visibilities, 'iterations': args.iterations, 'source_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in sources.items()}}
expected = {}
with sync_playwright() as p:
    executable = os.environ.get('MAUVE_CHROME_PATH')
    chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    if not executable and chrome.exists():
        executable = str(chrome)
    browser = p.chromium.launch(**({'executable_path': executable} if executable else {}))
    report['browser'] = browser.version
    for repeat in range(args.repeats):
        for label in (['baseline', 'candidate'] if repeat % 2 == 0 else ['candidate', 'baseline']):
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.route('**/static/app.js', lambda route: route.fulfill(body=sources[label], content_type='text/javascript'))
            page = context.new_page()
            page.goto(args.url)
            page.wait_for_function("typeof renderTrackControls === 'function'")
            cases = page.evaluate('''({genomeCounts, visibilities, iterations}) => {
              $('welcome').hidden = true; $('explorer').hidden = false;
              document.querySelector('.track-settings').open = true;
              const cases = [];
              for (const genomes of genomeCounts) for (const visibility of visibilities) {
                state.alignment = {genomes: Array.from({length: genomes}, (_, i) => ({id: i + 1, name: `Genome ${i + 1}`}))};
                state.order = state.alignment.genomes.map(g => g.id).reverse();
                state.hidden = new Set(state.order.filter(id => visibility === 'half' ? id % 2 : visibility === 'one' && id !== genomes));
                const renderControls = () => {renderTrackControls(); $('track-controls').getBoundingClientRect();};
                renderControls(); renderControls();
                const start = performance.now();
                for (let i = 0; i < iterations; i++) renderControls();
                const ms = (performance.now() - start) / iterations;
                const stateSnapshot = [...document.querySelectorAll('.track-control')].map(row => ({
                  id: row.dataset.genome, name: row.querySelector('label').textContent,
                  checked: row.querySelector('input').checked, disabled: row.querySelector('input').disabled,
                  buttons: [...row.querySelectorAll('button')].map(b => [b.getAttribute('aria-label'), b.disabled])}));
                if (stateSnapshot.filter(row => row.disabled).length !== (stateSnapshot.filter(row => row.checked).length === 1 ? 1 : 0))
                  throw Error('Last-visible-track protection changed');
                cases.push({genomes, visibility, ms, stateSnapshot});
              }
              return cases;
            }''', {'genomeCounts': genome_counts, 'visibilities': visibilities, 'iterations': args.iterations})
            for case in cases:
                snapshot = case.pop('stateSnapshot')
                key = f"{case['genomes']}/{case['visibility']}"
                if key in expected and expected[key] != snapshot:
                    raise RuntimeError('Track control state changed')
                expected[key] = snapshot
                report['runs'].append({'repeat': repeat, 'label': label, **case})
            context.close()
    browser.close()
report['medians_ms'] = {key: {label: statistics.median(r['ms'] for r in report['runs'] if r['label'] == label and f"{r['genomes']}/{r['visibility']}" == key) for label in sources} for key in expected}
report['states_identical'] = True
print(json.dumps(report, indent=2))
