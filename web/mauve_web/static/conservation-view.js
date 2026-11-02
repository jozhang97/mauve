// Only viewport samples cross the worker boundary. Keep one response and one
// outstanding request; rapid navigation replaces the queued viewport.
const conservationView = {key: null, data: null, pending: null, timer: null, desired: null, revision: 0, error: null};
function conservationBoxY(y, member) { return y + (displayedStrand(member.strand, member.genome_id) < 0 ? 9 : -15); }
// MatchPanel.getFillColorChangeHSB: base fill S-.2/V+.2, then
// lower fill S-.4/V+.5, range V+.3, mean line V-.2.
function conservationColors(hex) {
  const rgb = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(...rgb), min = Math.min(...rgb), delta = max - min;
  let hue = !delta ? 0 : max === rgb[0] ? (rgb[1]-rgb[2])/delta : max === rgb[1] ? 2+(rgb[2]-rgb[0])/delta : 4+(rgb[0]-rgb[1])/delta;
  hue = (hue + 6) % 6;
  const saturation = Math.max(0, (max ? delta / max : 0) - .2), brightness = Math.min(1, max + .2);
  const color = (ds, dv) => {
    const s = Math.max(0, saturation + ds), v = Math.min(1, brightness + dv);
    const c = v * s, x = c * (1-Math.abs(hue%2-1)), m = v-c;
    const values = [[c,x,0],[x,c,0],[0,c,x],[0,x,c],[x,0,c],[c,0,x]][Math.floor(hue)];
    return `rgb(${values.map(x=>Math.round((x+m)*255)).join(',')})`;
  };
  return {lower:color(-.4,.5), range:color(0,.3), mean:color(0,-.2)};
}

function queueConservation(key, aid, ranges) {
  conservationView.desired = {key, aid, ranges};
  clearTimeout(conservationView.timer);
  conservationView.timer = setTimeout(fetchConservation, 60);
}
async function fetchConservation() {
  clearTimeout(conservationView.timer);
  if (conservationView.pending) { await conservationView.pending; return fetchConservation(); }
  const request = conservationView.desired;
  if (!request || request.key === conservationView.key) return;
  conservationView.error = null;
  $('conservation-status').textContent = 'Computing conservation…';
  conservationView.pending = (async () => {
    try {
      const data = await api(`/api/alignments/${request.aid}/conservation`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(request.ranges)});
      if (conservationView.desired?.key === request.key && state.alignment?.id === request.aid) {
        conservationView.key = request.key; conservationView.data = data;
        $('conservation-status').textContent = 'Conservation across aligned genomes · mean line and shaded range; gaps reduce conservation.';
        render();
      }
    } catch (e) {
      if (conservationView.desired?.key === request.key) {
        conservationView.key = request.key; conservationView.data = null; conservationView.error = e;
        $('conservation-status').textContent = `Conservation unavailable: ${e.message}`;
      }
    } finally { conservationView.pending = null; }
  })();
  await conservationView.pending;
  if (conservationView.desired?.key !== conservationView.key) return fetchConservation();
}
function drawConservation(svg, project, ys, blocks, left, right) {
  if (!$('show-conservation').checked) { conservationView.desired = null; $('conservation-status').textContent = ''; return; }
  const ranges = [], geometry = [];
  for (const b of blocks) {
    if (b.members.length < 2) continue;
    for (const m of b.members) {
      if (!ys.has(m.genome_id)) continue;
      for (const copy of trackCopies(m.start, m.end, m.genome_id)) {
        const a = project(m.start, m.genome_id, copy), z = project(m.end + 1, m.genome_id, copy);
        const lo = Math.max(left, Math.min(a, z)), hi = Math.min(right, Math.max(a, z));
        if (hi <= lo) continue;
        const native = pixel => m.start + (pixel - a) / (z - a) * (m.end + 1 - m.start);
        const start = Math.max(m.start, Math.floor(Math.min(native(lo), native(hi))));
        const end = Math.min(m.end, Math.ceil(Math.max(native(lo), native(hi))) - 1);
        const bins = Math.max(1, Math.min(8192, Math.ceil(hi - lo)));
        ranges.push({genome_id: m.genome_id, start, end, bins}); geometry.push({b, m, copy});
      }
    }
  }
  const key = JSON.stringify([state.alignment.id, conservationView.revision, ranges]);
  queueConservation(key, state.alignment.id, ranges);
  if (key !== conservationView.key || !conservationView.data) return;
  const layer = svgNode('g', {'clip-path': 'url(#track-clip)', class: 'conservation-layer', 'pointer-events': 'none'});
  for (let gi = 0; gi < geometry.length; gi++) {
    const {b, m, copy} = geometry[gi], range = conservationView.data[gi], top = conservationBoxY(ys.get(m.genome_id), m), base = top + 23;
    const x = p => project(p, m.genome_id, copy), height = v => Math.max(0, Math.min(1, v)) * 22;
    const group = svgNode('g', {'clip-path': genomeClip(m.genome_id), 'data-block-id': b.id, 'data-genome': m.genome_id, class: 'conservation-profile'});
    let from = 0;
    while (from < range.samples.length) {
      const inside = range.samples[from][3]; let to = from + 1;
      while (to < range.samples.length && range.samples[to][3] === inside) to++;
      const tint = conservationColors(inside ? color(b.id) : '#808080'); let lower = '', band = '', line = '';
      for (let i = from; i < to; i++) {
        const [mean, min, max] = range.samples[i];
        const a = x(range.start + (range.end + 1 - range.start) * i / range.bins), z = x(range.start + (range.end + 1 - range.start) * (i + 1) / range.bins);
        const low = base - height(min), high = base - height(max), mid = base - height(mean);
        lower += `M${a},${base}V${low}H${z}V${base}Z`;
        band += `M${a},${low}V${high}H${z}V${low}Z`;
        line += `${i === from ? 'M' : 'L'}${(a+z)/2},${mid}`;
        if (to - from === 1) line = `M${a},${mid}L${z},${mid}`;
      }
      group.append(svgNode('path', {d: lower, fill: tint.lower, class: 'conservation-fill'}),
        svgNode('path', {d: band, fill: tint.range, class: 'conservation-range'}),
        svgNode('path', {d: line, fill: 'none', stroke: tint.mean, 'stroke-width': 1, class: 'conservation-mean', 'data-backbone': inside ? 'inside' : 'outside'}));
      from = to;
    }
    layer.append(group);
  }
  svg.append(layer);
}
