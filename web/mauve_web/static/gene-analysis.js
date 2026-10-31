"use strict";
(() => {
  const workerURL = new URL('./browser/gene-worker.mjs', document.currentScript.src);
  let worker, result, page = 0;
  const el = id => document.getElementById(id);
  const text = (tag, value) => { const node = document.createElement(tag); node.textContent = value; return node; };
  const percent = value => value === null ? 'N/A' : `${(100 * value).toFixed(1)}%`;
  const number = value => value === null ? 'N/A' : value.toLocaleString();
  const status = message => { el('gene-analysis-status').textContent = message; };
  const busy = active => { el('run-gene-analysis').disabled = active; el('cancel-gene-analysis').hidden = !active; };
  function stop() { worker?.terminate(); worker = null; busy(false); }
  function reset() {
    stop(); result = null; page = 0;
    el('gene-analysis-results').hidden = true;
    const genomes = state.alignment?.genomes || [];
    const missing = genomes.filter(g => !state.sources.some(s => s.genome_id === g.id));
    status(missing.length ? `Import GenBank annotations for ${missing.map(g => g.name).join(', ')} to compute all pairs.` : 'Ready to compare all genomes. Recompute after changing matching rules.');
  }
  window.mauveGeneAnalysis = {reset};
  for (const id of ['gene-coverage', 'gene-identity', 'gene-rna']) el(id).onchange = reset;
  el('cancel-gene-analysis').onclick = () => { stop(); status('Analysis canceled.'); };
  el('run-gene-analysis').onclick = () => {
    stop(); result = null; el('gene-analysis-results').hidden = true;
    if (!state.alignment) return;
    for (const id of ['gene-coverage', 'gene-identity']) if (!el(id).reportValidity()) return;
    const options = {coverage: Number(el('gene-coverage').value) / 100, identity: Number(el('gene-identity').value) / 100, rna: el('gene-rna').value};
    worker = new Worker(workerURL, {type: 'module'}); busy(true); status('Loading annotations and matching genes…');
    const active = worker;
    worker.onmessage = ({data}) => {
      if (worker !== active) return;
      if ('progress' in data && data.progress) status(data.progress);
      if (data.error) { stop(); status(data.error); }
      if (data.result) {
        result = data.result; stop(); page = 0;
        el('gene-family-search').value = '';
        render();
        const assumed = result.genomes.reduce((n, g) => n + g.assumed_circular, 0);
        status(`Computed ${number(result.pairs.length)} pairs across ${result.genomes.length} genomes. ${number(result.matched_pairs)} direct gene matches.${assumed ? ` ${assumed} record(s) lacked topology and were assumed circular.` : ''}`);
      }
    };
    worker.onerror = event => { if (worker === active) { stop(); status(`Analysis failed: ${event.message}`); } };
    worker.postMessage({aid: state.alignment.id, local: Boolean(window.mauveBrowser), base: new URL('./', document.baseURI).href, options});
  };
  function table(headers, rows) {
    const table = document.createElement('table'), head = document.createElement('thead'), tr = document.createElement('tr');
    for (const label of headers) { const th = text('th', label); th.scope = 'col'; tr.append(th); }
    head.append(tr); table.append(head);
    const body = document.createElement('tbody');
    for (const values of rows) { const row = document.createElement('tr'); for (const value of values) row.append(text('td', value)); body.append(row); }
    table.append(body); return table;
  }
  function renderHeatmap() {
    if (!result) return;
    const metric = el('gene-metric').value, fractional = ['content_jaccard', 'adjacency_jaccard', 'conservation'].includes(metric);
    const display = fractional ? percent : number;
    const max = fractional ? 1 : Math.max(1, ...result.pairs.map(p => p[metric] ?? 0));
    const pairs = new Map(result.pairs.map(p => [[p.a, p.b].sort((a, b) => a - b).join('/'), p]));
    const matrix = table(['Genome', ...result.genomes.map((g, i) => `${i + 1}. ${g.name}`)], []), body = matrix.tBodies[0];
    for (const [i, a] of result.genomes.entries()) {
      const row = document.createElement('tr'), label = text('th', `${i + 1}. ${a.name}`); label.scope = 'row'; row.append(label);
      for (const b of result.genomes) {
        const td = document.createElement('td');
        if (a.id === b.id) { td.textContent = '—'; td.title = 'Same genome'; }
        else {
          const pair = pairs.get([a.id, b.id].sort((a, b) => a - b).join('/')), value = pair[metric];
          td.textContent = display(value);
          td.title = `${a.name} / ${b.name}: ${display(value)}; ${pair.shared} shared / ${pair.union} distinct families; ${pair.order_genes} unique shared genes used for order; ${pair.excluded_shared} shared families excluded as duplicated`;
          if (value !== null) td.style.background = `rgba(155, 122, 188, ${0.08 + 0.55 * value / max})`;
        }
        row.append(td);
      }
      body.append(row);
    }
    el('gene-heatmap').replaceChildren(matrix);
    el('gene-heatmap-legend').textContent = `Darker cells indicate ${metric === 'dcj' ? 'greater distance (less conserved order)' : 'higher values'}. Scale: 0–${fractional ? '100%' : number(max)}. N/A means no eligible denominator. Hover for pair counts.`;
  }
  function renderFamilies() {
    if (!result) return;
    const query = el('gene-family-search').value.trim().toLowerCase();
    const families = result.families.filter(f => !query || [f.id, ...f.members.flatMap(m => [m.name, m.locus_tag])].join(' ').toLowerCase().includes(query));
    const pages = Math.max(1, Math.ceil(families.length / 50)); page = Math.min(page, pages - 1);
    const rows = families.slice(page * 50, (page + 1) * 50).map(f => [f.id, f.members[0]?.name || '', `${f.genomes}/${result.genomes.length}`, ...result.genomes.map(g => f.members.filter(m => m.genome_id === g.id).length)]);
    el('gene-family-table').replaceChildren(table(['Family', 'Example gene', 'Occupancy', ...result.genomes.map(g => g.name)], rows));
    el('gene-family-page').textContent = `${families.length} families · Page ${page + 1} of ${pages}`;
    el('gene-family-prev').disabled = page === 0; el('gene-family-next').disabled = page + 1 === pages;
  }
  function render() {
    el('gene-analysis-results').hidden = false;
    const names = new Map(result.genomes.map(g => [g.id, g.name]));
    el('gene-pair-table').replaceChildren(table(['Genome A', 'Genome B', 'Genes A / B', 'Families A / B', 'Shared / union', 'Content Jaccard', 'Actual adjacency Jaccard', 'Shared-order conservation', 'DCJ', 'Order genes / excluded families'],
      result.pairs.map(p => [names.get(p.a), names.get(p.b), `${p.genes_a} / ${p.genes_b}`, `${p.families_a} / ${p.families_b}`, `${p.shared} / ${p.union}`, percent(p.content_jaccard), `${percent(p.adjacency_jaccard)} (${p.adjacency_shared}/${p.adjacency_union})`, `${percent(p.conservation)} (${2 * p.preserved}/${p.neighbors_a + p.neighbors_b})`, number(p.dcj), `${p.order_genes} / ${p.excluded_shared}`])));
    el('gene-pan-summary').replaceChildren();
    for (const [label, key] of [['Pan families', 'pan'], ['Core families', 'core'], ['Single-copy core', 'single_copy_core'], ['Accessory families', 'accessory'], ['Genome-specific families', 'genome_specific'], ['Families with duplicates', 'duplicated_families']]) {
      const card = document.createElement('div'); card.append(text('strong', number(result[key])), text('span', label)); el('gene-pan-summary').append(card);
    }
    el('gene-genome-counts').replaceChildren(table(['Genome', 'Included gene loci', 'Other / excluded annotation features'], result.genomes.map(g => [g.name, number(g.genes), number(g.excluded_features)])));
    el('gene-occupancy').replaceChildren(); const max = Math.max(1, ...result.occupancy);
    result.occupancy.forEach((n, i) => {
      const row = document.createElement('div'); row.className = 'gene-occupancy-row';
      const bar = document.createElement('span'); bar.className = 'gene-occupancy-bar'; bar.style.width = `${100 * n / max}%`; bar.setAttribute('aria-hidden', 'true');
      const track = document.createElement('div'); track.append(bar);
      row.append(text('span', `${i + 1} genome${i ? 's' : ''}`), track, text('span', `${number(n)} families`)); el('gene-occupancy').append(row);
    });
    renderHeatmap(); renderFamilies();
  }
  el('gene-metric').onchange = renderHeatmap;
  el('gene-family-search').oninput = () => { page = 0; renderFamilies(); };
  el('gene-family-prev').onclick = () => { page--; renderFamilies(); };
  el('gene-family-next').onclick = () => { page++; renderFamilies(); };
  function download(content, filename, type) {
    const url = URL.createObjectURL(new Blob([content], {type})), link = document.createElement('a');
    link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const tsv = rows => rows.map(row => row.map(v => String(v ?? '').replace(/[\t\r\n]/g, ' ')).join('\t')).join('\n') + '\n';
  el('export-gene-pairs').onclick = () => {
    if (!result) return;
    const columns = Object.keys(result.pairs[0] || {});
    const names = new Map(result.genomes.map(g => [g.id, g.name]));
    download(tsv([['genome_a', 'genome_b', ...columns], ...result.pairs.map(p => [names.get(p.a), names.get(p.b), ...columns.map(k => p[k])])]), 'gene-pairs.tsv', 'text/tab-separated-values');
  };
  el('export-gene-families').onclick = () => {
    if (!result) return;
    const fields = ['genome_id', 'name', 'locus_tag', 'type', 'record', 'start', 'end', 'strand'];
    download(tsv([['family', 'genome_occupancy', ...fields], ...result.families.flatMap(f => f.members.map(m => [f.id, f.genomes, ...fields.map(k => m[k])]))]), 'gene-families.tsv', 'text/tab-separated-values');
  };
  el('export-gene-json').onclick = () => { if (result) download(JSON.stringify(result, null, 2), 'gene-analysis.json', 'application/json'); };
})();
