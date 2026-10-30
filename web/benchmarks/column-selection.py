"""Compare selecting columns in a large rendered sequence page."""
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
parser.add_argument('--candidate-app', type=Path, default=Path('web/mauve_web/static/app.js'))
args = parser.parse_args()
sources = {'baseline': args.baseline_app.read_text(), 'candidate': args.candidate_app.read_text()}
report = {'runs': [], 'genomes': 32, 'columns': 500, 'source_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in sources.items()}}
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
            page.wait_for_function("typeof renderBases === 'function'")
            data = page.evaluate('''() => {
              const genomes = 32, columns = 500;
              state.alignment = {genomes: Array.from({length: genomes}, (_, i) => ({id: i + 1, name: `Genome ${i + 1}`, extent: columns}))};
              state.order = state.alignment.genomes.map(g => g.id);
              state.hidden.clear(); state.profile = null; state.activeColumn = 0;
              state.detail = {offset: 0, columns, members: state.order.map(genome_id => ({genome_id,
                start: 1, end: columns, strand: '+', bases: 'ACGT'.repeat(columns / 4),
                positions: Array.from({length: columns}, (_, i) => i + 1)}))};
              $('welcome').hidden = true; $('explorer').hidden = false; $('differences-only').checked = false;
              const renderStart = performance.now();
              renderBases(); $('bases').getBoundingClientRect();
              const render_ms = performance.now() - renderStart;
              for (let i = 0; i < 5; i++) {selectColumn(i); $('bases').getBoundingClientRect();}
              const start = performance.now();
              for (let i = 5; i < 35; i++) {selectColumn(i); $('bases').getBoundingClientRect();}
              const selection_ms = (performance.now() - start) / 30;
              const buttons = [...document.querySelectorAll('#bases .base')];
              if (buttons.length !== genomes * columns || buttons.some(base => {
                const active = Number(base.dataset.column) === 34;
                return base.classList.contains('active-column') !== active ||
                  base.getAttribute('aria-pressed') !== String(active) || base.tabIndex !== (active ? 0 : -1);
              })) throw Error('Column selection state changed');
              const handlers = [...document.querySelectorAll('#bases *')].reduce((n, element) =>
                n + Number(Boolean(element.onclick)) + Number(Boolean(element.onkeydown)), 0);
              return {render_ms, selection_ms, buttons: buttons.length, handlers};
            }''')
            session = context.new_cdp_session(page)
            session.send('HeapProfiler.collectGarbage')
            data['retained_js_heap_bytes'] = session.send('Runtime.getHeapUsage')['usedSize']
            session.detach()
            report['runs'].append({'repeat': repeat, 'label': label, **data})
            context.close()
    browser.close()
report['medians_ms'] = {kind: {label: statistics.median(r[kind] for r in report['runs'] if r['label'] == label) for label in sources} for kind in ['render_ms', 'selection_ms']}
report['median_retained_js_heap_bytes'] = {label: statistics.median(r['retained_js_heap_bytes'] for r in report['runs'] if r['label'] == label) for label in sources}
print(json.dumps(report, indent=2))
