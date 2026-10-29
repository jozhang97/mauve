import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const source = readFileSync(new URL('../mauve_web/static/analytics.js', import.meta.url), 'utf8');
function setup(overrides = {}) {
  const scripts = [], calls = [];
  const context = {
    window: {MAUVE_ANALYTICS: {siteCode: 'test-site'}},
    location: {protocol: 'https:', hostname: 'example.org', search: '?private=data', hash: '#private-id'},
    navigator: {doNotTrack: '0'},
    document: {title: 'PRIVATE', referrer: 'https://private.example', createElement: () => ({dataset: {}}), head: {append: s => scripts.push(s)}},
    ...overrides,
  };
  runInNewContext(source, context);
  return {...context.window.mauveAnalytics, context, scripts, calls, load() {
    context.window.goatcounter.count = data => calls.push(JSON.parse(JSON.stringify(data)));
    scripts[0].onload();
  }};
}
test('tracking is disabled without build configuration, on local/HTTP previews, and with DNT', () => {
  for (const override of [
    {window: {}}, {window: {MAUVE_ANALYTICS: {siteCode: ''}}},
    {window: {MAUVE_ANALYTICS: {siteCode: 'https://invalid.example'}}},
    ...['localhost', '127.0.0.1', '[::1]', 'test.localhost'].map(hostname => ({location: {protocol: 'https:', hostname}})),
    {location: {protocol: 'http:', hostname: 'example.org'}}, {navigator: {doNotTrack: '1'}},
  ]) {
    const app = setup(override); app.trackUsage('demo-opened'); assert.equal(app.scripts.length, 0);
  }
});
test('visits and events use fixed Mauve labels only, including queued events', () => {
  const app = setup(); app.recordResponse('/api/alignments?name=SECRET.fa', {method: 'POST'});
  app.load(); app.scripts[0].onload();
  app.recordResponse('/api/jobs/secret-id'); // Polling cannot create usage events.
  app.recordResponse('/api/alignments/private-id');
  app.trackUsage('SECRET.fa');
  app.recordResponse('/api/ncbi/assemblies?taxon_id=SECRET&q=PRIVATE');
  app.recordDownload('/api/jobs/private-id/artifacts/manifest');
  assert.equal(app.scripts[0].dataset.goatcounter, 'https://test-site.goatcounter.com/count');
  assert.equal(app.scripts[0].referrerPolicy, 'no-referrer');
  assert.deepEqual(app.calls, [
    {path: '/mauve/', title: 'Mauve Explorer', referrer: ''},
    ...['alignment-imported', 'ncbi-search-completed', 'job-artifact-downloaded'].map(event => ({path: `mauve-${event}`, title: `mauve-${event}`, referrer: '', event: true, no_session: true})),
  ]);
});
test('successful operation mapping covers demo, annotations, submissions, and downloads', () => {
  const app = setup(); app.load();
  for (const route of ['/api/demo', '/api/alignments/private/genomes/2/annotations?name=private.gbk', '/api/jobs', '/api/ncbi/assemblies/PRIVATE/input']) app.recordResponse(route, {method:'POST'});
  app.recordDownload('/api/alignments/private/blocks/1/fasta');
  app.recordDownload('/api/alignments/private/blocks.tsv');
  app.trackUsage('alignment-completed'); app.trackUsage('svg-downloaded');
  assert.deepEqual(app.calls.slice(1).map(c => c.path), ['demo-opened', 'annotations-imported', 'alignment-submitted', 'ncbi-genome-downloaded', 'block-fasta-downloaded', 'block-table-downloaded', 'alignment-completed', 'svg-downloaded'].map(s => `mauve-${s}`));
});
test('blocked scripts, hanging loads, and tracker exceptions do not break app operations', () => {
  const app = setup(); for (let i=0;i<100;i++) app.trackUsage('demo-opened'); app.load(); assert.equal(app.calls.length, 21);
  app.context.window.goatcounter.count = () => { throw Error('offline'); };
  assert.doesNotThrow(() => app.trackUsage('svg-downloaded'));
  const blocked = setup(); blocked.scripts[0].onerror(); blocked.load(); blocked.trackUsage('demo-opened'); assert.equal(blocked.calls.length, 0);
  const denied = setup({document: {createElement: () => { throw Error('blocked'); }}});
  assert.doesNotThrow(() => denied.trackUsage('demo-opened'));
});
