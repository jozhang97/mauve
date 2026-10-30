"""Compare SVG rendering, retained JS heap, and exact SVG output on a static site."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--baseline-app', required=True, type=Path)
    parser.add_argument('--candidate-app', type=Path)
    parser.add_argument('--genomes', type=int, default=32)
    parser.add_argument('--blocks', type=int, default=500)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--view', action='append', choices=['full', 'zoomed'], help='Measure only the named view; default is both.')
    parser.add_argument('--identity-bins', type=int, default=0, help='Include the selected block identity overlay (0–200 bins).')
    args = parser.parse_args()
    views = args.view or ['full', 'zoomed']
    if not 0 <= args.identity_bins <= 200:
        parser.error('identity-bins must be between 0 and 200')
    if min(args.genomes, args.blocks, args.repeats) < 1:
        parser.error('genomes, blocks, and repeats must be positive')
    sources = {'baseline': args.baseline_app.read_text()}
    if args.candidate_app:
        sources['candidate'] = args.candidate_app.read_text()
    results = {'identity_bins': args.identity_bins, 'genomes': args.genomes, 'blocks': args.blocks, 'runs': [],
               'source_sha256': {label: hashlib.sha256(source.encode()).hexdigest() for label, source in sources.items()}}
    expected = {}
    with sync_playwright() as p:
        executable = os.environ.get('MAUVE_CHROME_PATH')
        chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        if not executable and chrome.exists():
            executable = str(chrome)
        browser = p.chromium.launch(**({'executable_path': executable} if executable else {}))
        results['browser'] = browser.version
        for repeat in range(args.repeats):
            for label in (['baseline', 'candidate'] if repeat % 2 == 0 else ['candidate', 'baseline']):
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                if label in sources:
                    context.route('**/static/app.js', lambda route: route.fulfill(body=sources[label], content_type='text/javascript'))
                page = context.new_page()
                page.goto(args.url)
                page.wait_for_function("typeof render === 'function'")
                page.evaluate('''({genomes, blocks, identityBins}) => {
                  state.alignment = {genomes: Array.from({length: genomes}, (_, i) =>
                    ({id: i + 1, name: `Genome ${i + 1}`, extent: blocks * 1000}))};
                  state.order = state.alignment.genomes.map(g => g.id);
                  state.hidden.clear(); state.detail = null; state.profile = null;
                  state.sources = []; state.features = []; state.selected = null;
                  clearBlockFilters(); $('links').checked = true;
                  $('welcome').hidden = true; $('explorer').hidden = false;
                  state.blocks = Array.from({length: blocks}, (_, i) => ({id: i + 1, columns: 500,
                    members: state.order.map(genome_id => ({genome_id,
                      start: i * 1000 + 1, end: i * 1000 + 500, strand: genome_id % 3 ? '+' : '-'}))}));
                  if (identityBins) {
                    state.selected = 1; $('show-identity').checked = true;
                    state.profile = {members: state.alignment.genomes.slice(1).map(g => ({genome_id: g.id,
                      windows: Array.from({length: identityBins}, (_, i) => ({
                        start: Math.floor(i * 500 / identityBins) + 1,
                        end: Math.floor((i + 1) * 500 / identityBins),
                        identity: i % 17 ? (i % 11) / 10 : null, compared: 2, columns: 3}))}))};
                  }
                }''', {'genomes': args.genomes, 'blocks': args.blocks, 'identityBins': args.identity_bins})
                timings = {}
                session = context.new_cdp_session(page)
                for name, start, end in [('full', 1, args.blocks * 1000), ('zoomed', 1, 1000)]:
                    if name not in views:
                        continue
                    data = page.evaluate('''async ({start, end}) => {
                      state.start = start; state.end = end;
                      render(); $('tracks').getBoundingClientRect();
                      const before = performance.now();
                      render(); $('tracks').getBoundingClientRect();
                      const result = {ms: performance.now() - before,
                        paths: document.querySelectorAll('#tracks svg path').length,
                        nodes: document.querySelectorAll('#tracks svg *').length};
                      const svg = document.querySelector('#tracks svg');
                      const handlers = [...svg.querySelectorAll('*')].flatMap(element =>
                        [element.onclick, element.onkeydown, element.ondblclick].filter(Boolean));
                      result.handlers = handlers.length;
                      result.distinct_handlers = new Set(handlers).size;
                      result.svg_sha256 = [...new Uint8Array(await crypto.subtle.digest('SHA-256',
                        new TextEncoder().encode(svg.outerHTML)))].map(x => x.toString(16).padStart(2, '0')).join('');
                      return result;
                    }''', {'start': start, 'end': end})
                    signature = (data['paths'], data['nodes'], data['svg_sha256'])
                    if name in expected and signature != expected[name]:
                        raise RuntimeError(f'SVG output changed for {name}')
                    expected[name] = signature
                    session.send('HeapProfiler.collectGarbage')
                    data['retained_js_heap_bytes'] = session.send('Runtime.getHeapUsage')['usedSize']
                    timings[name] = data
                session.detach()
                results['runs'].append({'engine': label, 'repeat': repeat, **timings})
                context.close()
        browser.close()
    for output, field in [('medians_ms', 'ms'), ('median_retained_js_heap_bytes', 'retained_js_heap_bytes')]:
        results[output] = {case: {label: statistics.median(run[case][field] for run in results['runs'] if run['engine'] == label)
                                 for label in ['baseline', 'candidate']} for case in views}
    results['svg_identical'] = True
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
