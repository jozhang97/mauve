"use strict";
(() => {
  const events = new Set([
    'demo-opened', 'alignment-imported', 'annotations-imported',
    'alignment-submitted', 'alignment-completed', 'ncbi-search-completed',
    'ncbi-genome-downloaded', 'block-fasta-downloaded', 'block-table-downloaded',
    'job-artifact-downloaded', 'svg-downloaded',
  ]);
  let enabled = false, ready = false;
  const pending = [];
  const optedOut = () => navigator.doNotTrack === '1' || window.doNotTrack === '1';
  function count(data) {
    if (optedOut()) return;
    try { window.goatcounter?.count?.(data); } catch { /* Counting must never interrupt the app. */ }
  }
  function trackUsage(event) {
    if (!enabled || optedOut() || !events.has(event)) return;
    if (!ready) { if (pending.length < 20) pending.push(event); return; }
    const label = `mauve-${event}`;
    count({path: label, title: label, referrer: '', event: true, no_session: true});
  }
  function recordResponse(path, options = {}) {
    // Match operations locally; never send paths, queries, IDs, or response data.
    const route = path.split('?')[0], post = options.method === 'POST';
    if (post && route === '/api/demo') trackUsage('demo-opened');
    else if (post && route === '/api/alignments') trackUsage('alignment-imported');
    else if (post && /^\/api\/alignments\/[^/]+\/genomes\/\d+\/annotations$/.test(route)) trackUsage('annotations-imported');
    else if (post && route === '/api/jobs') trackUsage('alignment-submitted');
    else if (!post && route === '/api/ncbi/assemblies') trackUsage('ncbi-search-completed');
    else if (post && /^\/api\/ncbi\/assemblies\/[^/]+\/input$/.test(route)) trackUsage('ncbi-genome-downloaded');
  }
  function recordDownload(path) {
    if (/^\/api\/alignments\/[^/]+\/blocks\/\d+\/fasta$/.test(path)) trackUsage('block-fasta-downloaded');
    else if (/^\/api\/alignments\/[^/]+\/blocks\.tsv$/.test(path)) trackUsage('block-table-downloaded');
    else if (/^\/api\/jobs\/[^/]+\/artifacts\/[^/]+$/.test(path)) trackUsage('job-artifact-downloaded');
  }
  window.mauveAnalytics = {trackUsage, recordResponse, recordDownload};
  const code = window.MAUVE_ANALYTICS?.siteCode || '';
  if (!/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(code) || location.protocol !== 'https:' ||
      ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname) || location.hostname.endsWith('.localhost') || optedOut()) return;
  try {
    window.goatcounter = {no_onload: true};
    const script = document.createElement('script');
    script.async = true; script.src = 'https://gc.zgo.at/count.js';
    script.dataset.goatcounter = `https://${code}.goatcounter.com/count`;
    script.referrerPolicy = 'no-referrer';
    script.onload = () => {
      if (ready || !enabled) return;
      ready = true;
      count({path: '/mauve/', title: 'Mauve Explorer', referrer: ''});
      pending.splice(0).forEach(trackUsage);
    };
    script.onerror = () => { enabled = false; pending.length = 0; };
    enabled = true;
    document.head.append(script);
  } catch { enabled = false; pending.length = 0; }
})();
