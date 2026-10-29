"use strict";
const $ = (id) => document.getElementById(id);
const colors = [
  "#9b7abc",
  "#76a998",
  "#c89965",
  "#719bbd",
  "#be819a",
  "#9aa966",
  "#8d8ac2",
  "#6fa9b0",
];
const state = {
  alignment: null,
  order: [],
  hidden: new Set(),
  reference: null,
  profile: null,
  profileEpoch: 0,
  detail: null,
  mapRevision: 0,
  linkedRevision: -1,
  activeColumn: null,
  pageSize: window.matchMedia("(max-width: 650px)").matches ? 25 : 100,
  blocks: [],
  selected: null,
  start: 1,
  end: 1,
  max: 1,
  offset: 0,
  epoch: 0,
  detailEpoch: 0,
  features: [],
  sources: [],
  featureEpoch: 0,
  searchEpoch: 0,
  selectedFeature: null,
};
const fmt = (n) => n.toLocaleString();
const color = (id) => colors[(id - 1) % colors.length];
function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").className = error ? "error" : "";
  $("notice").hidden = !message;
}
async function api(path, options) {
  const r = await fetch(path, options);
  if (!r.ok) {
    let body;
    try {
      body = await r.json();
    } catch {
      body = { detail: `Request failed (${r.status})` };
    }
    throw Error(
      typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body.detail),
    );
  }
  return r.json();
}
function safely(fn) {
  return async (...args) => {
    try {
      await fn(...args);
    } catch (e) {
      notice(e.message, true);
    }
  };
}
async function library() {
  const rows = await api("/api/alignments");
  $("library").replaceChildren();
  if (!rows.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = "Your next discovery starts here.";
    $("library").append(p);
  }
  for (const row of rows) {
    const b = document.createElement("button");
    b.textContent = row.name;
    b.title = row.name;
    b.className = row.id === state.alignment?.id ? "active" : "";
    b.onclick = safely(() => openAlignment(row.id));
    $("library").append(b);
  }
}
async function openAlignment(id) {
  const epoch = ++state.epoch;
  ++state.detailEpoch;
  ++state.featureEpoch;
  ++state.searchEpoch;
  notice("Loading alignment…");
  const [alignment, blocks, sources] = await Promise.all([
    api(`/api/alignments/${id}`),
    api(`/api/alignments/${id}/blocks`),
    api(`/api/alignments/${id}/annotations`),
  ]);
  if (epoch !== state.epoch) return;
  Object.assign(state, {
    alignment,
    order: alignment.genomes.map(g => g.id),
    hidden: new Set(),
    reference: alignment.genomes[0].id,
    profile: null,
    detail: null,
    mapRevision: 0,
    linkedRevision: -1,
    blocks,
    sources,
    features: [],
    selectedFeature: null,
    selected: null,
    offset: 0,
    start: 1,
    max: Math.max(
      ...alignment.genomes.map((g) => g.extent),
      ...sources.map((s) => s.metadata.length),
    ),
  });
  state.end = state.max;
  ++state.profileEpoch;
  $("reference-genome").replaceChildren();
  for (const g of alignment.genomes) {
    const option = document.createElement("option");
    option.value = g.id;
    option.textContent = g.name;
    $("reference-genome").append(option);
  }
  $("block-search").value = "";
  $("selection-status").textContent = "No block selected";
  $("jump-sequence").disabled = true;
  $("min-columns").value = 0;
  $("isolate-block").checked = false;
  $("shared-only").checked = false;
  $("focus-reference").disabled = true;
  $("identity-status").textContent = "Select a block to compare identity with the reference. Coordinates remain native to each genome.";
  renderTrackControls();
  $("welcome").hidden = true;
  $("explorer").hidden = false;
  $("title").textContent = alignment.name;
  $("subtitle").textContent =
    "Explore conserved blocks and sequence orientation. Track extents reflect coordinates present in this alignment.";
  $("genome-count").textContent = alignment.genomes.length;
  $("block-count").textContent = fmt(blocks.length);
  $("shared-count").textContent = fmt(
    blocks.filter((b) => b.members.length > 1).length,
  );
  $("export-fasta").hidden = true;
  $("export-blocks").href = `/api/alignments/${id}/blocks.tsv`;
  $("feature-results").replaceChildren();
  $("feature-detail").hidden = true;
  $("gene-query").value = "";
  $("concatenate-records").checked = false;
  $("annotation-genome").replaceChildren();
  for (const g of alignment.genomes) {
    const option = document.createElement("option");
    option.value = g.id;
    option.textContent = g.name;
    $("annotation-genome").append(option);
  }
  if (sources.length) $("annotation-genome").value = sources[0].genome_id;
  annotationStatus();
  $("block-title").textContent = "Select an alignment block";
  $("member-summary").replaceChildren();
  $("comparison-summary").replaceChildren();
  $("inspector-tools").hidden = true;
  $("sequence-navigation").hidden = true;
  $("sequence-scroll-hint").hidden = true;
  $("sequence-context").textContent = "";
  $("column-detail").hidden = true;
  $("differences-only").checked = false;
  $("bases").replaceChildren();
  $("inspection-hint").hidden = false;
  $("base-note").hidden = true;
  document.querySelector(".pager").hidden = true;
  history.replaceState(null, "", `#${id}`);
  render();
  renderList();
  window.scrollTo({top: 0, behavior: "instant"});
  $("title").tabIndex = -1;
  $("title").focus({preventScroll: true});
  updateSectionNavigation();
  notice("");
  await Promise.all([library(), loadFeatures()]);
}
function svgNode(tag, attrs = {}, content) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs))
    node.setAttribute(key, value);
  if (content !== undefined) node.textContent = content;
  return node;
}
function visibleGenomes() {
  return state.order.filter(id => !state.hidden.has(id)).map(id => state.alignment.genomes.find(g => g.id === id));
}
function sequenceMembers() {
  if (!state.detail) return [];
  return state.order.filter(id => !state.hidden.has(id))
    .map(id => state.detail.members.find(m => m.genome_id === id)).filter(Boolean);
}
function refreshTracks() {
  state.linkedRevision = -1;
  renderTrackControls(); render(); renderBases(); renderComparisonSummary();
}
function visibleBlocks() {
  return state.blocks.filter(b => b.columns >= Number($("min-columns").value || 0)
    && (!$("shared-only").checked || b.members.length > 1)
    && (!$("isolate-block").checked || state.selected === b.id));
}
function renderTrackControls() {
  $("track-controls").replaceChildren();
  state.order.forEach((id, index) => {
    const g = state.alignment.genomes.find(g => g.id === id);
    const row = document.createElement("div");
    row.className = "track-control";
    row.dataset.genome = id;
    const label = document.createElement("label"), check = document.createElement("input");
    check.type = "checkbox";
    check.checked = !state.hidden.has(id);
    check.disabled = check.checked && visibleGenomes().length === 1;
    check.onchange = () => {
      if (check.checked) state.hidden.delete(id); else state.hidden.add(id);
      refreshTracks();
    };
    label.append(check, document.createTextNode(g.name));
    row.append(label);
    for (const [delta, name] of [[-1, "Move up"], [1, "Move down"]]) {
      const button = document.createElement("button");
      button.textContent = delta < 0 ? "↑" : "↓";
      button.setAttribute("aria-label", `${name}: ${g.name}`);
      button.disabled = index + delta < 0 || index + delta >= state.order.length;
      button.onclick = () => {
        [state.order[index], state.order[index + delta]] = [state.order[index + delta], state.order[index]];
        refreshTracks();
      };
      row.append(button);
    }
    $("track-controls").append(row);
  });
}
async function loadProfile() {
  const token = ++state.profileEpoch;
  state.profile = null;
  $("comparison-summary").textContent = "";
  renderBases();
  render();
  const block = state.blocks.find(b => b.id === state.selected);
  $("focus-reference").disabled = !block?.members.some(m => m.genome_id === state.reference);
  if (!block) return;
  $("identity-status").textContent = "Calculating selected block identity…";
  try {
    const result = await api(`/api/alignments/${state.alignment.id}/blocks/${block.id}/profile?reference_id=${state.reference}`);
    if (token !== state.profileEpoch) return;
    state.profile = result;
    renderComparisonSummary();
    renderBases();
    $("identity-status").textContent = result.present
      ? `Block ${block.id} · Identity to reference, 0–100% per window. Only A/C/G/T pairs count; gaps and ambiguous bases excluded. Gray = no comparable bases. Native genomic coordinates.`
      : `Block ${block.id} is absent from the reference; no identity comparison is available.`;
    render();
  } catch (e) {
    if (token === state.profileEpoch) $("identity-status").textContent = `Identity unavailable: ${e.message}`;
  }
}
function renderComparisonSummary() {
  const target = $("comparison-summary");
  target.replaceChildren();
  const result = state.profile;
  if (!result) return;
  const heading = document.createElement("p");
  heading.className = "comparison-context";
  const ref = state.alignment.genomes.find(g => g.id === state.reference);
  heading.textContent = result.present
    ? `Reference: ${ref.name} · Whole-block identity is shown beside each sequence.`
    : "The comparison reference is absent from this block. Choose another reference above.";
  target.append(heading);
  if (!result.present || !result.members.length) return;
  const table = document.createElement("table");
  const header = document.createElement("tr");
  for (const title of ["Genome", "Identity", "Base substitutions", "Gap columns", "Ambiguous columns"]) {
    const th = document.createElement("th"); th.textContent = title; header.append(th);
  }
  table.append(header);
  for (const member of state.order.filter(id => !state.hidden.has(id)).map(id => result.members.find(m => m.genome_id === id)).filter(Boolean)) {
    const row = document.createElement("tr"), total = member.matches + member.substitutions;
    const name = state.alignment.genomes.find(g => g.id === member.genome_id).name;
    for (const value of [name, total ? `${(100 * member.matches / total).toFixed(2)}% (${fmt(total)} compared)` : "No comparable bases", fmt(member.substitutions), fmt(member.gap_columns), fmt(member.ambiguous_columns)]) {
      const td = document.createElement("td"); td.textContent = value; row.append(td);
    }
    table.append(row);
  }
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "Whole-block counts and comparison rules";
  const note = document.createElement("p");
  note.className = "small";
  note.textContent = "Identity uses A/C/G/T pairs only. Gaps and ambiguous bases are excluded. Counts are alignment columns, not variant calls or indel events; sequence highlighting compares all block members.";
  details.append(summary, note, table);
  target.append(details);
}
function renderBases() {
  const b = state.detail;
  if (!b) return;
  const target = $("bases"), scroll = target.scrollLeft;
  const members = sequenceMembers();
  target.replaceChildren();
  target.classList.toggle("isolated-differences", $("differences-only").checked);
  const differs = i => b.members.some(m => m.bases[i] !== b.members[0].bases[i]);
  const all = Array.from({length: b.members[0].bases.length}, (_, i) => i);
  const indices = all.filter(i => !$("differences-only").checked || differs(i));
  $("member-summary").textContent = `${members.length} of ${b.members.length} genomes visible · ${all.filter(differs).length} differing columns in this ${all.length}-column page${$("differences-only").checked ? " · Matching columns hidden; see alignment-column numbers for spacing" : " · Full sequence context"}`;
  if (!members.length) {
    target.textContent = "All genomes in this block are hidden. ";
    const reveal = document.createElement("button"); reveal.textContent = "Show block genomes";
    reveal.onclick = revealSelected; target.append(reveal);
    $("column-detail").hidden = true;
    $("sequence-scroll-hint").hidden = true;
    return;
  }
  if (!indices.length) {
    $("sequence-scroll-hint").hidden = true;
    target.textContent = "No differences in this page. Turn off ‘Isolate differences’ for sequence context, or skip to the next page with differences.";
    $("column-detail").hidden = true;
    return;
  }
  if (!indices.includes(state.activeColumn)) state.activeColumn = indices.find(differs) ?? indices[0];
  const ruler = document.createElement("div"); ruler.className = "base-row column-ruler";
  const rulerLabel = document.createElement("span"); rulerLabel.className = "base-label";
  rulerLabel.textContent = "Alignment column"; ruler.append(rulerLabel);
  for (const i of indices) {
    const tick = document.createElement("span"); tick.className = "column-tick";
    tick.textContent = $("differences-only").checked || (b.offset + i) % 10 === 0 ? fmt(b.offset + i + 1) : "";
    tick.title = `Alignment column ${fmt(b.offset + i + 1)}`;
    ruler.append(tick);
  }
  target.append(ruler);
  for (const m of sequenceMembers()) {
    const row = document.createElement("div"); row.className = "base-row sequence-row";
    row.dataset.genome = m.genome_id;
    const label = document.createElement("span"); label.className = "base-label";
    const name = document.createElement("strong");
    name.textContent = state.alignment.genomes.find(g => g.id === m.genome_id).name;
    name.title = name.textContent;
    name.dataset.short = `#${m.genome_id}`;
    const range = document.createElement("small");
    range.textContent = `${fmt(m.start)}–${fmt(m.end)} (${m.strand})`;
    const metric = document.createElement("small"); metric.className = "row-identity";
    const comparison = state.profile?.members.find(p => p.genome_id === m.genome_id);
    const total = comparison ? comparison.matches + comparison.substitutions : 0;
    metric.textContent = m.genome_id === state.reference ? "REFERENCE" : comparison
      ? total ? `${(100 * comparison.matches / total).toFixed(2)}% identity · ${fmt(total)} compared` : "No comparable A/C/G/T pairs"
      : state.profile && !state.profile.present ? "Reference absent from block" : "";
    label.append(name, range, metric); row.append(label);
    for (const i of indices) {
      const cell = document.createElement("span"); cell.className = "base-cell";
      const base = document.createElement("button");
      base.className = "base" + (differs(i) ? " diff" : "") + (m.bases[i] === "-" ? " gap" : "");
      base.textContent = m.bases[i];
      base.dataset.column = i;
      base.dataset.genome = m.genome_id;
      base.title = `${name.textContent} · Column ${b.offset + i + 1} · ${m.positions[i] === null ? "gap" : `genomic position ${fmt(m.positions[i])}`}`;
      base.setAttribute("aria-label", base.title + ` · ${m.bases[i]}`);
      base.onclick = () => selectColumn(i);
      base.onkeydown = e => {
        if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
        e.preventDefault();
        const next = indices[indices.indexOf(i) + (e.key === "ArrowLeft" ? -1 : 1)];
        if (next === undefined) return;
        selectColumn(next);
        row.querySelector(`[data-column="${next}"]`).focus();
      };
      cell.append(base); row.append(cell);
    }
    target.append(row);
  }
  target.scrollLeft = scroll;
  selectColumn(state.activeColumn);
  updateSequenceOverflow();
}
function selectColumn(index) {
  state.activeColumn = index;
  const b = state.detail, detail = $("column-detail");
  detail.replaceChildren(); detail.hidden = false;
  $("bases").querySelectorAll(".base").forEach(base => {
    const selected = Number(base.dataset.column) === index;
    base.classList.toggle("active-column", selected);
    base.setAttribute("aria-pressed", String(selected));
    base.tabIndex = selected ? 0 : -1;
  });
  const title = document.createElement("strong");
  const values = b.members.map(m => m.bases[index]);
  const category = values.every(v => v === values[0]) ? "Matching column"
    : values.includes("-") ? "Gap difference" : values.every(v => "ACGT".includes(v)) ? "Base difference" : "Difference includes ambiguity";
  title.textContent = `Column ${fmt(b.offset + index + 1)} · ${category}`;
  detail.append(title);
  const records = document.createElement("div"); records.className = "column-records";
  for (const m of sequenceMembers()) {
    const row = document.createElement("div");
    const name = state.alignment.genomes.find(g => g.id === m.genome_id).name;
    const position = m.positions[index];
    const label = document.createElement("span");
    label.textContent = `${name}: ${m.bases[index]} · ${position === null ? "gap, no genomic coordinate" : fmt(position) + " bp (" + m.strand + ")"}`;
    row.append(label);
    const comparison = state.profile?.members.find(p => p.genome_id === m.genome_id);
    if (comparison) {
      const metric = document.createElement("small"), total = comparison.matches + comparison.substitutions;
      metric.textContent = total ? `${(100 * comparison.matches / total).toFixed(2)}% whole-block identity; ${fmt(total)} compared bases` : "No comparable A/C/G/T pairs";
      row.append(metric);
    }
    if (position !== null) {
      const focus = document.createElement("button"); focus.textContent = "View locus";
      focus.setAttribute("aria-label", `View ${name} at ${position}`);
      focus.onclick = () => {
        state.hidden.delete(m.genome_id); renderTrackControls();
        setRange(position - 100, position + 100, false);
        $("tracks").scrollIntoView({behavior: "smooth", block: "center"});
      };
      row.append(focus);
    }
    records.append(row);
  }
  detail.append(records);
}
function drawIdentity(svg, x, ys) {
  if (!state.profile || !$("show-identity").checked || !visibleBlocks().some(b => b.id === state.selected)) return;
  const layer = svgNode("g", {"clip-path": "url(#track-clip)", class: "identity-layer"});
  svg.append(layer);
  for (const m of state.profile.members) {
    if (!ys.has(m.genome_id)) continue;
    const baseline = ys.get(m.genome_id) + 18;
    for (const w of m.windows) {
      if (w.end < state.start || w.start > state.end) continue;
      const rect = svgNode("rect", {
        x: x(w.start), y: baseline - (w.identity === null ? 18 : w.identity * 18),
        width: Math.max(.5, x(w.end + 1) - x(w.start)),
        height: w.identity === null ? 18 : Math.max(.6, w.identity * 18),
        fill: w.identity === null ? "var(--muted)" : "var(--text)",
        opacity: w.identity === null ? .35 : .65,
        class: "identity-window",
      });
      rect.append(svgNode("title", {}, `${fmt(w.start)}–${fmt(w.end)} · ${w.identity === null ? "No comparable bases" : (w.identity * 100).toFixed(1) + "% identity"} · ${w.compared}/${w.columns} comparable columns`));
      rect.onclick = safely(() => selectBlock(state.selected, state.offset));
      layer.append(rect);
    }
  }
}
function render() {
  if (!state.alignment) return;
  const width = Math.max(660, $("tracks").clientWidth - 24),
    left = 180,
    right = width - 26,
    top = 55,
    gap = $("show-annotations").checked && state.sources.length ? 152 : 112;
  const genomes = visibleGenomes(), blocks = visibleBlocks();
  const filters = Number($("min-columns").value) > 0 || $("isolate-block").checked || $("shared-only").checked;
  $("display-settings").querySelector("summary").textContent = filters ? "Display & filters · filters active" : "Display & filters";
  const height = top + genomes.length * gap;
  const svg = svgNode("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "group",
    "aria-label": "Aligned genome tracks",
  });
  const defs = svgNode("defs");
  const clip = svgNode("clipPath", { id: "track-clip" });
  clip.append(svgNode("rect", { x: left, y: 0, width: right - left, height }));
  defs.append(clip);
  const pattern = svgNode("pattern", {
    id: "reverse-hatch",
    width: 6,
    height: 6,
    patternUnits: "userSpaceOnUse",
    patternTransform: "rotate(45)",
  });
  pattern.append(
    svgNode("line", {
      x1: 0,
      y1: 0,
      x2: 0,
      y2: 6,
      stroke: "#ffffff",
      "stroke-opacity": ".45",
      "stroke-width": 2,
    }),
  );
  defs.append(pattern);
  svg.append(defs);
  const span = state.end - state.start + 1,
    x = (p) => left + ((p - state.start) / span) * (right - left),
    ys = new Map();
  genomes.forEach((g, i) => ys.set(g.id, top + i * gap));
  const connections = svgNode("g", { "clip-path": "url(#track-clip)" });
  svg.append(connections);
  if ($("links").checked)
    for (const b of blocks) {
      const ms = b.members.filter(m => ys.has(m.genome_id)).sort(
        (a, c) => ys.get(a.genome_id) - ys.get(c.genome_id),
      );
      for (let i = 1; i < ms.length; i++) {
        const a = ms[i - 1],
          c = ms[i];
        const ends = (m) =>
          m.strand === "+"
            ? [x(m.start), x(m.end + 1)]
            : [x(m.end + 1), x(m.start)];
        const [a1, a2] = ends(a),
          [c1, c2] = ends(c),
          y1 = ys.get(a.genome_id) + 18,
          y2 = ys.get(c.genome_id);
        connections.append(
          svgNode("path", {
            d: `M${a1},${y1} L${a2},${y1} L${c2},${y2} L${c1},${y2} Z`,
            fill: color(b.id),
            opacity:
              state.selected === b.id
                ? "var(--link-selected-opacity)"
                : "var(--link-opacity)",
          }),
        );
      }
    }
  for (const g of genomes) {
    const y = ys.get(g.id);
    let name = g.name.replace(/\.(fasta|fas|fa|gbk|gb|raw)$/i, "");
    const label = svgNode(
      "text",
      { x: 10, y: y + 6, class: "genome-name" },
      name.length > 23 ? name.slice(0, 21) + "…" : name,
    );
    label.append(svgNode("title", {}, g.name));
    svg.append(
      label,
      svgNode(
        "text",
        { x: 10, y: y + 24, class: "tick" },
        `#${g.id}${g.id === state.reference ? " · REF" : ""} · ${fmt(g.extent)} bp extent`,
      ),
    );
    svg.append(
      svgNode("line", {
        x1: left,
        x2: right,
        y1: y + 9,
        y2: y + 9,
        stroke: "var(--track-line)",
        "stroke-width": 2,
      }),
    );
    for (let t = 0; t <= 4; t++) {
      const p = Math.round(state.start + ((span - 1) * t) / 4),
        tx = x(p);
      svg.append(
        svgNode(
          "text",
          {
            x: tx,
            y: y + 41,
            class: "tick",
            "text-anchor": t === 4 ? "end" : "start",
          },
          fmt(p),
        ),
      );
    }
  }
  const rectangles = svgNode("g", { "clip-path": "url(#track-clip)" });
  svg.append(rectangles);
  for (const b of blocks)
    for (const m of b.members) {
      if (!ys.has(m.genome_id)) continue;
      if (m.end < state.start || m.start > state.end) continue;
      const y = ys.get(m.genome_id),
        attrs = {
          x: x(m.start),
          y,
          width: Math.max(2, x(m.end + 1) - x(m.start)),
          height: 18,
          rx: 3,
        };
      const r = svgNode("rect", {
        ...attrs,
        fill: color(b.id),
        class: "block",
        tabindex: 0,
        role: "button",
        "aria-label": `Block ${b.id}, sequence ${m.genome_id}, ${m.start} to ${m.end}, ${m.strand === "+" ? "forward" : "reverse"} strand`,
        stroke: state.selected === b.id ? "var(--selection-outline)" : "none",
        "stroke-width": 2,
      });
      r.append(
        svgNode(
          "title",
          {},
          `Block ${b.id} · ${fmt(m.start)}–${fmt(m.end)} · ${m.strand}`,
        ),
      );
      r.onclick = safely(() => selectBlock(b.id));
      r.onkeydown = safely((e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          return selectBlock(b.id);
        }
      });
      r.ondblclick = () =>
        setRange(
          m.start - (m.end - m.start) * 0.12,
          m.end + (m.end - m.start) * 0.12,
        );
      rectangles.append(r);
      if (m.strand === "-")
        rectangles.append(
          svgNode("rect", {
            ...attrs,
            fill: "url(#reverse-hatch)",
            "pointer-events": "none",
          }),
        );
    }
  drawIdentity(svg, x, ys);
  if (state.detail?.id === state.selected && blocks.some(b => b.id === state.selected)) {
    const layer = svgNode("g", {"clip-path": "url(#track-clip)", class: "sequence-page-markers"});
    for (const member of sequenceMembers()) {
      const positions = member.positions.filter(p => p !== null);
      if (!positions.length || !ys.has(member.genome_id)) continue;
      const start = Math.min(...positions), end = Math.max(...positions);
      const marker = svgNode("rect", {x: x(start), y: ys.get(member.genome_id) + 23,
        width: Math.max(3, x(end + 1) - x(start)), height: 4, fill: "var(--purple)", class: "page-window"});
      marker.append(svgNode("title", {}, `Sequence page: ${fmt(start)}–${fmt(end)} bp · alignment columns ${fmt(state.offset + 1)}–${fmt(state.offset + member.bases.length)}`));
      layer.append(marker);
    }
    svg.append(layer);
  }
  drawAnnotations(svg, x, ys);
  $("tracks").replaceChildren(svg);
  $("range").textContent = `${fmt(state.start)}–${fmt(state.end)} bp`;
  $("region").value = `${state.start}-${state.end}`;
  updateMapFeedback();
}
function setRange(start, end, sync = true) {
  ++state.mapRevision;
  const span = Math.min(state.max, Math.max(1, Math.round(end - start + 1)));
  state.start = Math.max(1, Math.min(state.max - span + 1, Math.round(start)));
  state.end = state.start + span - 1;
  state.features = [];
  render();
  safely(loadFeatures)();
  if (sync && state.selected) safely(inspectVisibleRegion)();
  else state.linkedRevision = state.mapRevision;
}
function zoom(factor) {
  const center = (state.start + state.end) / 2,
    span = (state.end - state.start + 1) * factor;
  setRange(center - span / 2, center + span / 2 - 1);
}
function renderList() {
  $("block-list").replaceChildren();
  const query = $("block-search").value.trim().toLowerCase();
  const blocks = visibleBlocks().filter(b => !query || String(b.id) === query
    || `block ${b.id}`.includes(query)
    || b.members.some(m => state.alignment.genomes.find(g => g.id === m.genome_id).name.toLowerCase().includes(query)));
  $("block-results-count").textContent = `${fmt(blocks.length)} of ${fmt(state.blocks.length)}`;
  if (!blocks.length) {
    const empty = document.createElement("p"); empty.className = "small";
    empty.textContent = "No matching blocks. Clear the search or adjust Display & filters.";
    $("block-list").append(empty);
  }
  for (const b of blocks) {
    const button = document.createElement("button");
    const title = document.createElement("strong"), meta = document.createElement("small");
    title.textContent = `Block ${b.id}`;
    meta.textContent = `${fmt(b.columns)} columns · ${b.members.length} genome${b.members.length === 1 ? "" : "s"}`;
    button.append(title, meta);
    button.setAttribute("aria-pressed", String(state.selected === b.id));
    button.style.setProperty("--block-color", color(b.id));
    button.className = state.selected === b.id ? "selected" : "";
    button.onclick = safely(() => selectBlock(b.id));
    $("block-list").append(button);
  }
}
async function selectBlock(id, offset = null, location = null, followPage = false) {
  if (offset === null) {
    const block = state.blocks.find(b => b.id === id);
    location = state.start === 1 && state.end === state.max ? null : mapLocation(block);
    offset = 0;
  }
  const params = new URLSearchParams({offset, limit: state.pageSize});
  if (location) { params.set("genome_id", location.genome_id); params.set("position", location.position); }
  const token = ++state.detailEpoch,
    aid = state.alignment.id;
  const b = await api(
    `/api/alignments/${aid}/blocks/${id}?${params}`,
  );
  if (token !== state.detailEpoch || aid !== state.alignment.id) return;
  // An older running backend ignores new query parameters. Never accept a
  // response that silently resolves a genomic jump to the wrong base.
  if (location && b.members.find(m => m.genome_id === location.genome_id)?.positions[0] !== location.position) {
    $("sequence-context").textContent = "The previous sequence page is retained. Genomic navigation is waiting for the server update.";
    throw Error("Genomic-position navigation requires a server restart. Let running alignment jobs finish before restarting the app.");
  }
  $("export-fasta").hidden = false;
  $("export-fasta").href = `/api/alignments/${aid}/blocks/${id}/fasta`;
  const changedBlock = state.selected !== id;
  state.selected = id;
  $("selection-status").textContent = `Block ${id} · ${fmt(b.columns)} columns`;
  $("jump-sequence").disabled = false;
  if (changedBlock) loadProfile();
  offset = b.offset;
  state.offset = offset;
  render();
  renderList();
  $("block-title").textContent =
    `Block ${id} · ${fmt(b.columns)} alignment columns`;
  $("inspection-hint").hidden = true;
  $("base-note").hidden = false;
  document.querySelector(".pager").hidden = false;
  $("columns").textContent =
    `${fmt(offset + 1)}–${fmt(Math.min(offset + state.pageSize, b.columns))}`;
  $("previous").disabled = offset === 0;
  $("next").disabled = offset + state.pageSize >= b.columns;
  $("member-summary").replaceChildren();
  $("bases").replaceChildren();
  state.detail = b;
  state.activeColumn = location ? 0 : null;
  $("bases").scrollLeft = 0;
  $("sequence-navigation").hidden = false;
  $("page-size").value = state.pageSize;
  const genomeValue = $("sequence-genome").value;
  $("sequence-genome").replaceChildren();
  for (const member of b.members) {
    const option = document.createElement("option"); option.value = member.genome_id;
    option.textContent = state.alignment.genomes.find(g => g.id === member.genome_id).name;
    $("sequence-genome").append(option);
  }
  if (b.members.some(m => String(m.genome_id) === genomeValue)) $("sequence-genome").value = genomeValue;
  else if (b.members.some(m => m.genome_id === state.reference)) $("sequence-genome").value = state.reference;
  $("sequence-context").textContent = location
    ? `Linked to genome #${location.genome_id} at ${fmt(location.position)} bp. Purple marks under map tracks show this sequence page.`
    : "Purple marks under map tracks show this sequence page. Jump by alignment column or genomic position.";
  if ($("sequence-location-kind").value === "column") $("sequence-position").value = offset + 1;
  $("inspector-tools").hidden = false;
  $("difference-status").textContent = "";
  renderBases();
  if (followPage) focusSequencePage();
  state.linkedRevision = state.mapRevision;
  render();
}
$("differences-only").onchange = renderBases;
$("next-difference").onclick = safely(async () => {
  const aid = state.alignment.id, bid = state.selected, epoch = state.detailEpoch;
  $("difference-status").textContent = "Finding next difference…";
  const result = await api(`/api/alignments/${aid}/blocks/${bid}/next-difference?after=${state.offset + state.pageSize}`);
  if (epoch !== state.detailEpoch || aid !== state.alignment.id) return;
  if (result.offset === null) $("difference-status").textContent = "No more differences after this page.";
  else await selectBlock(bid, result.offset, null, true);
});

const demo = safely(async () => {
  notice("Opening demo…");
  const a = await api("/api/demo", { method: "POST" });
  await openAlignment(a.id);
});
$("demo").onclick = demo;
$("welcome-demo").onclick = demo;
$("import").onclick = () => $("file").click();
$("file").onchange = safely(async () => {
  const file = $("file").files[0];
  if (!file) return;
  try {
    if (file.size > 256 * 1024 * 1024)
      throw Error("This version supports alignment files up to 256 MiB.");
    $("import").disabled = true;
    notice(`Importing ${file.name}…`);
    const a = await api(
      `/api/alignments?name=${encodeURIComponent(file.name)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
      },
    );
    await openAlignment(a.id);
  } finally {
    $("import").disabled = false;
    $("file").value = "";
  }
});
function mapLocation(block) {
  if (!block) return null;
  const members = block.members.filter(m => !state.hidden.has(m.genome_id) && m.end >= state.start && m.start <= state.end);
  const member = members.find(m => m.genome_id === state.reference) || members[0];
  return member ? {genome_id: member.genome_id, position: member.strand === "+" ? Math.max(member.start, state.start) : Math.min(member.end, state.end)} : null;
}
async function inspectVisibleRegion() {
  if (!state.selected || state.linkedRevision === state.mapRevision) return;
  const block = state.blocks.find(b => b.id === state.selected);
  const location = mapLocation(block);
  if (!location) {
    ++state.detailEpoch;
    $("sequence-context").textContent = "The selected block has no visible member in this map region. Its last sequence page is retained; reveal the block or jump to a position below.";
    return;
  }
  await selectBlock(state.selected, 0, location);
}
function focusSequencePage(preferredId = state.reference) {
  const members = sequenceMembers();
  const member = members.find(m => m.genome_id === preferredId && m.positions.some(p => p !== null))
    || members.find(m => m.positions.some(p => p !== null));
  if (!member) return;
  const positions = member.positions.filter(p => p !== null);
  const start = Math.min(...positions), end = Math.max(...positions);
  setRange(start - 20, end + 20, false);
}
function clearBlockFilters() {
  $("min-columns").value = 0;
  $("shared-only").checked = $("isolate-block").checked = false;
  $("block-search").value = "";
}
function revealSelected() {
  const block = state.blocks.find(b => b.id === state.selected);
  if (!block) return;
  clearBlockFilters();
  for (const member of block.members) state.hidden.delete(member.genome_id);
  refreshTracks(); renderList();
  const start = Math.min(...block.members.map(m => m.start));
  const end = Math.max(...block.members.map(m => m.end));
  setRange(start, end);
}
function updateMapFeedback() {
  const blocks = visibleBlocks();
  const hasMembers = blocks.some(b => b.members.some(m => !state.hidden.has(m.genome_id)));
  const inRegion = blocks.some(b => b.members.some(m => !state.hidden.has(m.genome_id) && m.end >= state.start && m.start <= state.end));
  $("map-feedback").hidden = inRegion;
  $("map-feedback-text").textContent = !blocks.length ? "No blocks match these filters. Fit all changes the coordinate range, not filters."
    : !hasMembers ? "All genomes containing these blocks are hidden." : "No blocks are visible in this coordinate range.";
  $("clear-map-filters").textContent = !blocks.length ? "Clear filters" : !hasMembers ? "Show all genomes" : "Fit all";
  $("clear-map-filters").dataset.action = !blocks.length ? "filters" : !hasMembers ? "tracks" : "range";
  const selected = state.blocks.find(b => b.id === state.selected);
  const filtered = selected && !blocks.some(b => b.id === selected.id);
  const hidden = selected && !selected.members.some(m => !state.hidden.has(m.genome_id));
  $("selection-feedback").hidden = !filtered && !hidden;
  $("selection-feedback-text").textContent = `Block ${state.selected} is hidden by ${filtered ? "filters" : "track visibility"}. Its sequence remains open below.`;
  $("identity-status").hidden = Boolean(filtered || hidden);
  if (selected) $("selection-status").textContent = `Block ${selected.id}${filtered || hidden ? " · hidden on map" : ` · ${fmt(selected.columns)} columns`}`;
}
function updateSequenceOverflow() {
  $("sequence-scroll-hint").hidden = !state.detail || $("bases").scrollWidth <= $("bases").clientWidth + 1;
}
$("clear-map-filters").onclick = () => {
  const action = $("clear-map-filters").dataset.action;
  if (action === "filters") { clearBlockFilters(); render(); renderList(); }
  else if (action === "tracks") { state.hidden.clear(); refreshTracks(); }
  else setRange(1, state.max);
};
$("reveal-selected").onclick = revealSelected;
$("sequence-location-kind").onchange = () => {
  $("sequence-genome").hidden = $("sequence-location-kind").value !== "genomic";
  if ($("sequence-location-kind").value === "column") $("sequence-position").value = state.offset + 1;
};
$("sequence-jump").onsubmit = safely(async event => {
  event.preventDefault();
  const position = Number($("sequence-position").value);
  if (!Number.isSafeInteger(position) || position < 1) throw Error("Enter a positive whole-number position.");
  const genomic = $("sequence-location-kind").value === "genomic";
  const gid = Number($("sequence-genome").value);
  await selectBlock(state.selected, genomic ? 0 : position - 1, genomic ? {genome_id: gid, position} : null, true);
  if (genomic) { state.hidden.delete(gid); refreshTracks(); focusSequencePage(gid); state.linkedRevision = state.mapRevision; }
  notice("");
});
$("page-size").onchange = safely(async () => {
  state.pageSize = Number($("page-size").value);
  if (state.selected) await selectBlock(state.selected, state.offset);
});
$("full-sequence-labels").onchange = () => {
  $("bases").classList.toggle("full-labels", $("full-sequence-labels").checked);
  updateSequenceOverflow();
};
new ResizeObserver(updateSequenceOverflow).observe($("bases"));

function goToSection(id) {
  const target = $(id);
  target.scrollIntoView({behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start"});
  target.tabIndex = -1;
  target.focus({preventScroll: true});
}
document.querySelectorAll("[data-section]").forEach(button => {
  button.onclick = safely(async () => {
    if (button.dataset.section === "sequence-panel") await inspectVisibleRegion();
    goToSection(button.dataset.section);
  });
});
$("jump-sequence").onclick = safely(async () => { await inspectVisibleRegion(); goToSection("sequence-panel"); });
$("block-search").oninput = renderList;
$("reset-display").onclick = () => {
  for (const id of ["links", "show-annotations", "show-identity"]) $(id).checked = true;
  $("isolate-block").checked = $("shared-only").checked = false;
  $("min-columns").value = 0;
  $("block-search").value = "";
  state.order = state.alignment.genomes.map(g => g.id);
  state.hidden.clear();
  renderTrackControls(); renderList(); loadProfile();
};
let navigationFrame = null;
function updateSectionNavigation() {
  navigationFrame = null;
  if (!state.alignment) return;
  const sections = ["overview-panel", "sequence-panel", "annotations-panel"];
  const activeId = sections.filter(id => $(id).getBoundingClientRect().top <= 150).at(-1) || sections[0];
  document.querySelectorAll("[data-section]").forEach(button => {
    const active = button.dataset.section === activeId;
    button.classList.toggle("current", active);
    if (active) button.setAttribute("aria-current", "location"); else button.removeAttribute("aria-current");
  });
}
window.addEventListener("scroll", () => {
  if (navigationFrame === null) navigationFrame = requestAnimationFrame(updateSectionNavigation);
}, {passive: true});
window.addEventListener("resize", updateSectionNavigation);
$("links").onchange = render;
$("shared-only").onchange = () => { render(); renderList(); };
$("min-columns").oninput = $("isolate-block").onchange = () => { render(); renderList(); };
$("reference-genome").onchange = () => {
  state.reference = Number($("reference-genome").value);
  loadProfile();
};
$("show-identity").onchange = loadProfile;
$("focus-reference").onclick = () => {
  const member = state.blocks.find(b => b.id === state.selected)?.members.find(m => m.genome_id === state.reference);
  if (!member) return;
  state.hidden.delete(state.reference);
  renderTrackControls();
  const margin = Math.max(10, (member.end - member.start) * .1);
  setRange(member.start - margin, member.end + margin);
};
$("zoom-in").onclick = () => zoom(0.5);
$("zoom-out").onclick = () => zoom(2);
$("reset").onclick = () => setRange(1, state.max);
$("pan-left").onclick = () => {
  const d = (state.end - state.start + 1) * 0.3;
  setRange(state.start - d, state.end - d);
};
$("pan-right").onclick = () => {
  const d = (state.end - state.start + 1) * 0.3;
  setRange(state.start + d, state.end + d);
};
$("region-form").onsubmit = (e) => {
  e.preventDefault();
  const m = $("region")
    .value.replaceAll(",", "")
    .match(/^\s*(\d+)\s*[-–:]\s*(\d+)\s*$/);
  if (!m || +m[1] < 1 || +m[2] < +m[1] || +m[2] > state.max) {
    notice(
      `Enter a range between 1 and ${fmt(state.max)}, such as 1-${Math.min(1000, state.max)}.`,
      true,
    );
    return;
  }
  notice("");
  setRange(+m[1], +m[2]);
};
$("previous").onclick = safely(() =>
  selectBlock(state.selected, Math.max(0, state.offset - state.pageSize), null, true),
);
$("next").onclick = safely(() =>
  selectBlock(state.selected, state.offset + state.pageSize, null, true),
);
function annotationStatus() {
  const gid = Number($("annotation-genome").value);
  const source = state.sources.find((s) => s.genome_id === gid);
  $("annotation-status").textContent = source
    ? `${source.name} · ${fmt(source.metadata.feature_count)} features · ${source.metadata.records.length} record(s) · ${fmt(source.metadata.verified_bases)} canonical aligned bases checked. Importing replaces these annotations.`
    : "Choose the genome matching your GenBank sequence. Imports are checked against aligned DNA and replace this genome’s annotations.";
}
async function loadFeatures() {
  if (!state.alignment) return;
  const token = ++state.featureEpoch,
    aid = state.alignment.id;
  const result = await api(
    `/api/alignments/${aid}/features?start=${state.start}&end=${state.end}&limit=500`,
  );
  if (token !== state.featureEpoch || aid !== state.alignment.id) return;
  state.features = result.items;
  $("feature-limit").hidden = result.total <= 500;
  $("feature-limit").textContent =
    `Showing 500 of ${fmt(result.total)} features in this region. Zoom in or search to find additional features.`;
  render();
}
function drawAnnotations(svg, x, ys) {
  if (!$("show-annotations").checked) return;
  const layer = svgNode("g", { "clip-path": "url(#track-clip)" });
  svg.append(layer);
  for (const source of state.sources) {
    if (!ys.has(source.genome_id)) continue;
    const y = ys.get(source.genome_id);
    for (const record of source.metadata.records) {
      if (record.start > state.end || record.end < state.start) continue;
      const boundary = svgNode("line", {
        x1: x(record.start),
        x2: x(record.start),
        y1: y + 21,
        y2: y + 106,
        stroke: "var(--record-boundary)",
        "stroke-dasharray": "2 3",
      });
      boundary.append(
        svgNode(
          "title",
          {},
          `${record.name}: ${fmt(record.start)}–${fmt(record.end)}`,
        ),
      );
      layer.append(boundary);
    }
  }
  const lanes = new Map();
  for (const f of state.features) {
    if (!ys.has(f.genome_id)) continue;
    if (!lanes.has(f.genome_id)) lanes.set(f.genome_id, [0, 0, 0]);
    const occupied = lanes.get(f.genome_id);
    let lane = occupied.findIndex((end) => end < f.start);
    // Dense features share the last lane; searchable details remain available.
    if (lane < 0) lane = 2;
    occupied[lane] = Math.max(occupied[lane], f.end);
    const y = ys.get(f.genome_id) + 55 + lane * 17;
    if (f.parts.length > 1)
      layer.append(
        svgNode("line", {
          x1: x(f.start),
          x2: x(f.end + 1),
          y1: y + 5,
          y2: y + 5,
          stroke: "var(--feature-line)",
          "stroke-dasharray": "2 2",
        }),
      );
    for (const part of f.parts) {
      if (part.end < state.start || part.start > state.end) continue;
      const a = x(part.start),
        b = Math.max(a + 3, x(part.end + 1)),
        tip = Math.min(6, (b - a) / 2);
      const points =
        part.strand === "+"
          ? `${a},${y} ${b - tip},${y} ${b},${y + 5} ${b - tip},${y + 10} ${a},${y + 10}`
          : part.strand === "-"
            ? `${a + tip},${y} ${b},${y} ${b},${y + 10} ${a + tip},${y + 10} ${a},${y + 5}`
            : `${a},${y} ${b},${y} ${b},${y + 10} ${a},${y + 10}`;
      const node = svgNode("polygon", {
        points,
        fill:
          f.id === state.selectedFeature
            ? "var(--feature-selected)"
            : "var(--feature)",
        stroke: part.fuzzy ? "var(--feature-line)" : "none",
        "stroke-dasharray": part.fuzzy ? "2 2" : "none",
        class: "feature",
        role: "button",
        tabindex: 0,
        "aria-label": `${f.name}, ${f.type}, ${f.start} to ${f.end}`,
      });
      node.append(
        svgNode(
          "title",
          {},
          `${f.name} · ${f.type} · ${fmt(part.start)}–${fmt(part.end)} (${part.strand})${part.fuzzy ? " · approximate boundary" : ""}`,
        ),
      );
      node.onclick = () => showFeature(f);
      node.onkeydown = (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          showFeature(f);
        }
      };
      layer.append(node);
    }
  }
}
function showFeature(f, focus = false) {
  state.selectedFeature = f.id;
  const detail = $("feature-detail");
  detail.replaceChildren();
  detail.hidden = false;
  const heading = document.createElement("h3");
  heading.textContent = `${f.name} · ${f.type}`;
  detail.append(heading);
  const genome = state.alignment.genomes.find((g) => g.id === f.genome_id);
  const lines = [
    `${genome.name} · ${f.record} · ${fmt(f.start)}–${fmt(f.end)} (${f.strand})`,
    f.locus_tag ? `Locus tag: ${f.locus_tag}` : "",
    f.product,
    f.note,
    f.parts.length > 1
      ? `Compound feature: ${f.parts.map((p) => `${fmt(p.start)}–${fmt(p.end)} (${p.strand})`).join(", ")}`
      : "",
    f.parts.some((p) => p.fuzzy)
      ? "Approximate boundary: displayed at the GenBank boundary estimate."
      : "",
  ];
  for (const line of lines.filter(Boolean)) {
    const p = document.createElement("p");
    p.textContent = line;
    detail.append(p);
  }
  const button = document.createElement("button");
  button.textContent = "Focus this feature";
  button.onclick = () => showFeature(f, true);
  detail.append(button);
  if (focus) {
    state.hidden.delete(f.genome_id);
    renderTrackControls();
    const margin = Math.max(20, (f.end - f.start) * 0.15);
    setRange(f.start - margin, f.end + margin);
  } else render();
}
async function searchFeatures(offset = 0) {
  const token = ++state.searchEpoch,
    aid = state.alignment.id;
  const params = new URLSearchParams({
    q: $("gene-query").value,
    genome_id: $("annotation-genome").value,
    limit: 50,
    offset,
  });
  const result = await api(`/api/alignments/${aid}/features?${params}`);
  if (token !== state.searchEpoch || aid !== state.alignment.id) return;
  const target = $("feature-results");
  if (offset === 0) target.replaceChildren();
  target.querySelector(".more-results")?.remove();
  if (offset === 0) {
    const p = document.createElement("p");
    p.className = "small";
    p.textContent = result.total
      ? `${fmt(result.total)} matching features. Select one to focus its region.`
      : "No matching features. Import GenBank annotations or try another search.";
    target.append(p);
  }
  for (const f of result.items) {
    const b = document.createElement("button");
    b.textContent = `${f.name} · ${f.type} · ${fmt(f.start)}–${fmt(f.end)}`;
    b.onclick = () => showFeature(f, true);
    target.append(b);
  }
  if (offset + 50 < result.total) {
    const b = document.createElement("button");
    b.className = "more-results";
    b.textContent = "Load more results";
    b.onclick = safely(() => searchFeatures(offset + 50));
    target.append(b);
  }
}
$("annotation-genome").onchange = () => {
  ++state.searchEpoch;
  $("feature-results").replaceChildren();
  annotationStatus();
};
$("gene-query").oninput = () => {
  ++state.searchEpoch;
  $("feature-results").replaceChildren();
};
$("feature-search").onsubmit = safely((e) => {
  e.preventDefault();
  return searchFeatures();
});
$("show-annotations").onchange = render;
$("import-annotations").onclick = () => $("annotation-file").click();
$("annotation-file").onchange = safely(async () => {
  const file = $("annotation-file").files[0];
  if (!file) return;
  const aid = state.alignment.id,
    gid = $("annotation-genome").value;
  try {
    if (file.size > 50 * 1024 * 1024)
      throw Error("This version supports files up to 50 MiB.");
    $("import-annotations").disabled = true;
    notice(`Checking annotations in ${file.name}…`);
    const params = new URLSearchParams({
      name: file.name,
      concatenate: $("concatenate-records").checked,
    });
    const result = await api(
      `/api/alignments/${aid}/genomes/${gid}/annotations?${params}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
      },
    );
    if (aid !== state.alignment?.id) return;
    const sources = await api(`/api/alignments/${aid}/annotations`);
    if (aid !== state.alignment?.id) return;
    state.sources = sources;
    state.max = Math.max(
      ...state.alignment.genomes.map((g) => g.extent),
      ...state.sources.map((s) => s.metadata.length),
    );
    state.selectedFeature = null;
    $("feature-detail").hidden = true;
    $("feature-results").replaceChildren();
    ++state.searchEpoch;
    annotationStatus();
    await loadFeatures();
    notice(
      `Imported ${fmt(result.feature_count)} features. Verified ${fmt(result.verified_bases)} canonical aligned bases.`,
    );
  } finally {
    $("import-annotations").disabled = false;
    $("annotation-file").value = "";
  }
});
$("export-svg").onclick = () => {
  const source = $("tracks").querySelector("svg"),
    clone = source.cloneNode(true);
  const originals = [source, ...source.querySelectorAll("*")],
    copies = [clone, ...clone.querySelectorAll("*")];
  originals.forEach((node, i) => {
    const style = getComputedStyle(node);
    for (const key of [
      "fill",
      "stroke",
      "stroke-width",
      "stroke-dasharray",
      "opacity",
      "fill-opacity",
      "stroke-opacity",
      "font-family",
      "font-size",
      "font-weight",
    ]) {
      copies[i].style.setProperty(key, style.getPropertyValue(key));
    }
    copies[i].removeAttribute("tabindex");
    copies[i].removeAttribute("role");
  });
  const box = source.viewBox.baseVal;
  clone.setAttribute("width", box.width);
  clone.setAttribute("height", box.height);
  clone.insertBefore(
    svgNode("rect", {
      width: "100%",
      height: "100%",
      fill: getComputedStyle(document.documentElement)
        .getPropertyValue("--surface")
        .trim(),
    }),
    clone.firstChild,
  );
  clone.insertBefore(
    svgNode(
      "title",
      {},
      `${state.alignment.name} · ${state.start}–${state.end} bp`,
    ),
    clone.firstChild,
  );
  clone.insertBefore(
    svgNode(
      "desc",
      {},
      "Genomic coordinates are 1-based inclusive. Colors denote alignment blocks; hatching denotes reverse strands. Green arrows are GenBank features; selected features are purple. Dark bars within the selected block show canonical-pair identity to the chosen reference (0–100%); gaps and ambiguous bases are excluded. Gray windows have no comparable bases. Purple marks below tracks indicate the current sequence page. Coordinates remain native to each genome. This export captures the current visible overview.",
    ),
    clone.firstChild,
  );
  const url = URL.createObjectURL(
    new Blob([new XMLSerializer().serializeToString(clone)], {
      type: "image/svg+xml",
    }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = "mauve-overview.svg";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

new ResizeObserver(() => render()).observe($("tracks"));
safely(async () => {
  await library();
  if (location.hash.length > 1) await openAlignment(location.hash.slice(1));
})();
