"""Compare browser XMFA parsing for wrapped and unwrapped sequence lines."""
import argparse
import json
import os
from pathlib import Path
import statistics

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--baseline-core', type=Path, required=True)
    parser.add_argument('--genomes', type=int, default=2)
    parser.add_argument('--columns', type=int, default=5000000)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if min(args.genomes, args.columns, args.repeats) < 1:
        parser.error('Use positive genomes, columns, and repeats')
    result = {'genomes': args.genomes, 'columns': args.columns, 'runs': []}
    baseline = args.baseline_core.read_text()
    expected = None
    with sync_playwright() as p:
        executable = os.environ.get('MAUVE_CHROME_PATH')
        chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        if not executable and chrome.exists():
            executable = str(chrome)
        browser = p.chromium.launch(**({'executable_path': executable} if executable else {}))
        result['browser'] = browser.version
        for repeat in range(args.repeats):
            for label in (['baseline', 'candidate'] if repeat % 2 == 0 else ['candidate', 'baseline']):
                context = browser.new_context()
                # Parser-only harness: keep application workers out of the
                # measurement and allow comparison against older module APIs.
                context.route(args.url, lambda route: route.fulfill(
                    body='<!doctype html><title>Parser benchmark</title>', content_type='text/html'))
                if label == 'baseline':
                    context.route('**/static/browser/core.mjs', lambda route: route.fulfill(body=baseline, content_type='text/javascript'))
                page = context.new_page()
                page.goto(args.url)
                data = page.evaluate('''async ({genomes, columns}) => {
                  const {parseXMFA} = await import('./static/browser/core.mjs');
                  const sequence = 'acgtN--'.repeat(Math.ceil(columns / 7)).slice(0, columns);
                  const residues = sequence.replaceAll('-', '').length;
                  const results = [];
                  const digest = async bytes => [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
                    .map(b => b.toString(16).padStart(2, '0')).join('');
                  for (const width of [0, 80]) {
                    const wrapped = width ? sequence.match(/.{1,80}/g).join('\\n') : sequence;
                    const blob = new Blob(Array.from({length: genomes}, (_, i) =>
                      `> ${i + 1}:1-${residues} ${i % 2 ? '-' : '+'} genome-${i + 1}.fa\\n${wrapped}\\n`).concat('=\\n'));
                    await parseXMFA(blob, () => {});
                    const blocks = [], start = performance.now();
                    const metadata = await parseXMFA(blob, block => blocks.push(block));
                    const ms = performance.now() - start;
                    if (metadata.genomes.length !== genomes || blocks.length !== 1 ||
                        metadata.genomes.some(g => g.extent !== residues)) throw Error('Metadata mismatch');
                    const hashes = [];
                    for (const member of blocks[0].members) hashes.push({sequence: await digest(member.sequence), prefix: await digest(member.prefix)});
                    results.push({width, ms, metadata, hashes});
                  }
                  return results;
                }''', {'genomes': args.genomes, 'columns': args.columns})
                for case in data:
                    signature = {'metadata': case.pop('metadata'), 'hashes': case.pop('hashes')}
                    if expected is None:
                        expected = signature
                    if signature != expected:
                        raise RuntimeError('Parsed sequences, indexes, or metadata differ')
                    result['runs'].append({'label': label, 'repeat': repeat, **case})
                context.close()
        browser.close()
    result['output'] = expected
    result['median_ms'] = {str(width): {label: statistics.median(run['ms'] for run in result['runs']
        if run['label'] == label and run['width'] == width) for label in ['baseline', 'candidate']}
        for width in [0, 80]}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
