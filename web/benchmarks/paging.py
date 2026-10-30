"""Compare real IndexedDB sequence paging on a block exceeding the 64 MiB cache."""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--baseline-store', type=Path, required=True)
    parser.add_argument('--baseline-worker', type=Path, required=True)
    parser.add_argument('--genomes', type=int, default=128)
    parser.add_argument('--columns', type=int, default=750000)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if args.genomes < 1 or args.columns < 5000 or args.repeats < 1:
        parser.error('Use positive genomes/repeats and at least 5000 columns')
    result = {'genomes': args.genomes, 'columns': args.columns, 'runs': []}
    baseline_store = args.baseline_store.read_text()
    baseline_worker = args.baseline_worker.read_text()
    with sync_playwright() as p:
        executable = os.environ.get('MAUVE_CHROME_PATH')
        chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        if not executable and chrome.exists():
            executable = str(chrome)
        browser = p.chromium.launch(**({'executable_path': executable} if executable else {}))
        result['browser'] = browser.version
        for repeat in range(args.repeats):
            for label in (['baseline', 'candidate'] if repeat % 2 == 0 else ['candidate', 'baseline']):
                print(f'{label} repeat {repeat}: starting', file=sys.stderr, flush=True)
                context = browser.new_context()
                if label == 'baseline':
                    context.route('**/static/browser/store.mjs', lambda route: route.fulfill(body=baseline_store, content_type='text/javascript'))
                    context.route('**/static/browser/worker.mjs', lambda route: route.fulfill(body=baseline_worker, content_type='text/javascript'))
                page = context.new_page()
                page.goto(args.url)
                page.evaluate("mauveBrowser.request('/api/alignments')")
                timings = page.evaluate('''async ({genomes, columns}) => {
                  const sequence = 'ACGT'.repeat(Math.ceil(columns / 4)).slice(0, columns);
                  const wrapped = sequence.match(/.{1,80}/g).join('\\n');
                  const blob = new Blob(Array.from({length: genomes}, (_, i) =>
                    `> ${i + 1}:1-${columns} ${i % 2 ? '-' : '+'} genome-${i + 1}.fa\\n${wrapped}\\n`).concat('=\\n'));
                  const alignment = await mauveBrowser.request('/api/alignments?name=paging-benchmark', {method: 'POST', body: blob});
                  const times = [];
                  for (let step = 0; step < 4; ++step) {
                    const offset = step * 997;
                    const start = performance.now();
                    const data = await mauveBrowser.request(`/api/alignments/${alignment.id}/blocks/1?offset=${offset}&limit=100`);
                    times.push(performance.now() - start);
                    if (data.members.length !== genomes) throw Error('Missing page member');
                    for (const member of data.members) {
                      const first = member.strand === '+' ? offset + 1 : columns - offset;
                      const direction = member.strand === '+' ? 1 : -1;
                      if (member.bases !== sequence.slice(offset, offset + 100) || member.positions.length !== 100 ||
                          member.positions.some((p, i) => p !== first + direction * i)) throw Error('Page mismatch');
                    }
                  }
                  return {cold_ms: times[0], warm_ms: times.slice(1)};
                }''', {'genomes': args.genomes, 'columns': args.columns})
                result['runs'].append({'label': label, 'repeat': repeat, **timings})
                print(f'{label} repeat {repeat}: {timings}', file=sys.stderr, flush=True)
                context.close()
        browser.close()
    result['median_warm_ms'] = {label: statistics.median(
        time for run in result['runs'] if run['label'] == label for time in run['warm_ms'])
        for label in ['baseline', 'candidate']}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
