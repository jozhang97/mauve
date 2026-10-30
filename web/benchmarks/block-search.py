"""Compare block search and list rendering with repeated genome memberships."""
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
args = parser.parse_args()
sources = {'baseline': args.baseline_app.read_text(), 'candidate': Path('web/mauve_web/static/app.js').read_text()}
report = {'runs': [], 'genomes': 64, 'blocks': 1000, 'source_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in sources.items()}}
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
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.route('**/static/app.js', lambda route: route.fulfill(body=sources[label], content_type='text/javascript'))
            page = context.new_page()
            page.goto(args.url)
            page.wait_for_function("typeof renderList === 'function'")
            cases = page.evaluate('''() => {
              state.alignment = {genomes: Array.from({length: 64}, (_, i) => ({id: i + 1, name: `Genome ${i + 1} Müller`, extent: 1000000}))};
              state.order = state.alignment.genomes.map(g => g.id);
              state.hidden.clear(); state.selected = null;
              state.blocks = Array.from({length: 1000}, (_, i) => ({id: i + 1, columns: 500,
                members: state.order.filter(id => i % 3 || id % 2).map(genome_id => ({genome_id}))}));
              clearBlockFilters(); $('welcome').hidden = true; $('explorer').hidden = false;
              const measured = ['', 'absent species', 'genome 64', 'block 12', 'MÜLLER'].map(query => {
                $('block-search').value = query;
                renderList(); $('block-list').getBoundingClientRect();
                const start = performance.now();
                renderList(); $('block-list').getBoundingClientRect();
                const ms = performance.now() - start;
                const names = [...document.querySelectorAll('#block-list button strong')].map(n => n.textContent);
                return {query, ms, names};
              });
              state.blocks = [{id: 1, columns: 20, members: [{}]},
                {id: 2, columns: 50, members: [{}, {}]}, {id: 3, columns: 100, members: [{}]}];
              const checks = [
                [0, false, false, null, [1, 2, 3]], [50, false, false, null, [2, 3]],
                [0, true, false, null, [2]], [0, false, true, 1, [1]],
                [50, false, true, 1, []], [0, false, true, null, []],
                [50, true, true, 2, [2]]];
              for (const [minimum, shared, isolated, selected, expected] of checks) {
                $('min-columns').value = minimum; $('shared-only').checked = shared;
                $('isolate-block').checked = isolated; state.selected = selected;
                if (JSON.stringify(visibleBlocks().map(b => b.id)) !== JSON.stringify(expected))
                  throw Error('Block filter results changed');
              }
              return measured;
            }''')
            for case in cases:
                names = case.pop('names')
                if case['query'] in expected and expected[case['query']] != names:
                    raise RuntimeError('Search results changed')
                expected[case['query']] = names
                report['runs'].append({'repeat': repeat, 'label': label, 'matches': len(names), **case})
            context.close()
    browser.close()
report['medians_ms'] = {query: {label: statistics.median(r['ms'] for r in report['runs'] if r['label'] == label and r['query'] == query) for label in sources} for query in expected}
report['results_identical'] = True
report['filter_checks_per_context'] = 7
print(json.dumps(report, indent=2))
