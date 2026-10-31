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
  profileError: null,
  profileEpoch: 0,
  detail: null,
  mapRevision: 0,
  linkedRevision: -1,
  activeColumn: null,
  pageSize: window.matchMedia("(max-width: 650px)").matches ? 25 : 100,
  blocks: [],
  selected: null,
  trackOffsets: new Map(),
  trackDirections: new Map(),
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
  if (window.mauveBrowser) return window.mauveBrowser.request(path, options);
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
  state.trackOffsets.clear();
  state.trackDirections.clear();
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
    profileError: null,
    detail: null,
    mapRevision: 0,
    linkedRevision: -1,
    blocks,
    sources,
    features: [],
    selectedFeature: null,
    selected: null,
    trackOffsets: new Map(),
    trackDirections: new Map(),
    offset: 0,
    start: 1,
    max: Math.max(
      ...alignment.genomes.map((g) => g.extent),
      ...sources.map((s) => s.metadata.length),
    ),
  });
  state.end = state.max;
  window.mauveGeneAnalysis?.reset();
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
  $("zoom-selected").disabled = true;
  $("min-columns").value = 0;
  $("isolate-block").checked = false;
  $("shared-only").checked = false;
  $("focus-reference").disabled = true;
  $("identity-status").textContent = "Select a block to compare identity with the reference. Coordinate labels remain native to each genome.";
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
function sequenceReversed() {
  const members = state.detail?.members || [];
  const reference = members.find(m => m.genome_id === state.reference) || members[0];
  return $("orient-tracks").checked && reference?.strand === "-";
}
function displayBase(base) {
  if (!sequenceReversed()) return base;
  const alphabet = "ACGTRYMKBDHVSWN-acgtrymkbdhvswn";
  const complement = "TGCAYRKMVHDBSWN-tgcayrkmvhdbswn";
  const i = alphabet.indexOf(base);
  return i < 0 ? base : complement[i];
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
  const minimum = Number($("min-columns").value || 0), shared = $("shared-only").checked,
    isolated = $("isolate-block").checked, selected = state.selected;
  return state.blocks.filter(b => b.columns >= minimum
    && (!shared || b.members.length > 1)
    && (!isolated || selected === b.id)
    && (!$("core-genes-only").checked || !window.mauveGeneAnalysis?.result || coreBlockIds.has(b.id)));
}
let coreGeneKeys = new Set(), coreBlockIds = new Set();
function refreshCoreGenes() {
  const result = window.mauveGeneAnalysis?.result;
  const index = window.mauveTrackGeometry.coreIndex(result, state.blocks);
  coreGeneKeys = index.geneKeys;
  coreBlockIds = index.blockIds;
  if ($("core-genes-only").checked && result && coreBlockIds.size) {
    // An isolated accessory block must not hide every core-containing block.
    if ($("isolate-block").checked && !coreBlockIds.has(state.selected))
      $("isolate-block").checked = false;
    const members = visibleBlocks().flatMap(b => b.members).filter(m => !state.hidden.has(m.genome_id));
    if (members.length && !members.some(m => trackVisible(m.start, m.end, m.genome_id)))
      // Preserve alignment offsets and orientation when fitting filtered tracks.
      setRange(1, state.max, false);
  }
  updateCoreGeneStatus();
  if (state.alignment) { render(); renderList(); }
}
function updateCoreGeneStatus() {
  const enabled = $("core-genes-only").checked, result = window.mauveGeneAnalysis?.result;
  $("core-genes-status").hidden = !enabled;
  $("core-genes-status").textContent = !enabled ? "" : result
    ? `Core genes only · ${fmt(result.core)} families present in all ${result.genomes.length} genomes (including hidden tracks). Only blocks overlapping a core gene are shown (${fmt(coreBlockIds.size)} of ${fmt(state.blocks.length)}). All gene copies are included; arrows show the selected block.`
    : `Core genes only · Showing all blocks while core-family results are unavailable; gene arrows are hidden until comparisons finish. ${window.mauveGeneAnalysis?.status || "Compute gene comparisons below."}`;
}
$("core-genes-only").onchange = () => {
  if ($("core-genes-only").checked) $("show-annotations").checked = true;
  refreshCoreGenes();
  if ($("core-genes-only").checked && !window.mauveGeneAnalysis?.result)
    $("run-gene-analysis").click();
};
window.addEventListener("mauve-gene-analysis", refreshCoreGenes);
window.addEventListener("mauve-gene-analysis-status", () => {
  updateCoreGeneStatus();
  if (state.alignment) updateMapFeedback();
});
function trackDistance(id) {
  if (id === state.reference) return 0;
  const pair = window.mauveGeneAnalysis?.result?.pairs.find(p =>
    (p.a === state.reference && p.b === id) || (p.b === state.reference && p.a === id));
  return Number.isFinite(pair?.dcj) ? pair.dcj : null;
}
function applyTrackOrder() {
  if (!state.alignment) return;
  if ($("track-sort").value === "manual") { $("track-sort-status").textContent = "Manual track order"; return; }
  state.hidden.delete(state.reference);
  const available = window.mauveGeneAnalysis?.result;
  const ranks = new Map(state.alignment.genomes.map((g,i) => [g.id,i]));
  state.order.sort((a,b) => a === b ? 0 : a === state.reference ? -1 : b === state.reference ? 1
    : available ? (trackDistance(a) ?? Infinity) - (trackDistance(b) ?? Infinity) || ranks.get(a)-ranks.get(b)
      : ranks.get(a)-ranks.get(b));
  $("track-sort-status").textContent = available
    ? "Reference first · lowest DCJ first · unavailable values last"
    : window.mauveGeneAnalysis?.status || "Run gene comparisons below to compute DCJ distances.";
}
function refreshTrackOrder() {
  applyTrackOrder();
  if (state.alignment) { renderTrackControls(); render(); renderBases(); renderComparisonSummary(); }
}
$("track-sort").onchange = () => {
  refreshTrackOrder();
  if ($("track-sort").value === "dcj" && !window.mauveGeneAnalysis?.result)
    $("run-gene-analysis").click();
};
window.addEventListener("mauve-gene-analysis", refreshTrackOrder);
window.addEventListener("mauve-gene-analysis-status", () => {
  if ($("track-sort").value === "dcj" && !window.mauveGeneAnalysis?.result)
    $("track-sort-status").textContent = window.mauveGeneAnalysis?.status || "Computing DCJ distances…";
});
function renderTrackControls() {
  $("track-controls").replaceChildren();
  const visibleCount = state.order.reduce((count, id) => count + !state.hidden.has(id), 0);
  state.order.forEach((id, index) => {
    const g = state.alignment.genomes.find(g => g.id === id);
    const row = document.createElement("div");
    row.className = "track-control";
    row.dataset.genome = id;
    const label = document.createElement("label"), check = document.createElement("input");
    check.type = "checkbox";
    check.checked = !state.hidden.has(id);
    check.disabled = (check.checked && visibleCount === 1) || ($("track-sort").value === "dcj" && id === state.reference);
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
        $("track-sort").value = "manual"; applyTrackOrder();
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
  state.profileError = null;
  applyTrackOrder();
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
    applyTrackOrder(); renderTrackControls();
    renderComparisonSummary();
    renderBases();
    $("identity-status").textContent = result.present
      ? `Block ${block.id} · Whole-block nucleotide identity vs ${state.alignment.genomes.find(g => g.id === state.reference).name} is shown beside each track; bars show identity per window. Only A/C/G/T pairs count; gaps and ambiguous bases excluded. Gray = no comparable bases.`
      : `Block ${block.id} is absent from the reference; no identity comparison is available.`;
    render();
  } catch (e) {
    if (token === state.profileEpoch) {
      state.profileError = e.message;
      $("identity-status").textContent = `Identity unavailable: ${e.message}`;
      render();
    }
  }
}
function selectedBlockIdentity(genomeId) {
  const block = state.blocks.find(b => b.id === state.selected);
  if (!block) return null;
  const reference = state.alignment.genomes.find(g => g.id === state.reference);
  const context = `Block ${block.id} · Compared with ${reference.name}`;
  const unavailable = value => ({value, detail: `Block ${block.id}`, title: `${context} · ${value}`});
  if (!block.members.some(m => m.genome_id === genomeId)) return unavailable('Absent from block');
  if (!block.members.some(m => m.genome_id === state.reference)) return unavailable('N/A · reference absent');
  if (genomeId === state.reference) return unavailable('Reference');
  if (state.profileError) return {...unavailable('Identity unavailable'), title: `${context} · ${state.profileError}`};
  if (!state.profile) return unavailable('Calculating identity…');
  const member = state.profile.members.find(m => m.genome_id === genomeId);
  if (!member) return unavailable('Identity unavailable');
  const compared = member.matches + member.substitutions;
  if (!compared) return unavailable('N/A · no comparable bases');
  const value = `${(100 * member.matches / compared).toFixed(2)}% block identity`;
  return {value, detail: `Block ${block.id} · ${fmt(compared)} pairs`,
    title: `${context} · ${value} · ${fmt(member.matches)} matches / ${fmt(compared)} comparable A/C/G/T pairs. ${fmt(member.gap_columns)} gap columns and ${fmt(member.ambiguous_columns)} ambiguous columns excluded. Whole highlighted block, independent of zoom or sequence page.`};
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
  const differences = Array.from({length: b.members[0].bases.length}, (_, i) => b.members.some(m => m.bases[i] !== b.members[0].bases[i]));
  const differs = i => differences[i];
  const all = Array.from({length: b.members[0].bases.length}, (_, i) => i);
  const indices = all.filter(i => !$("differences-only").checked || differs(i));
  if (sequenceReversed()) indices.reverse();
  $("base-note").textContent = sequenceReversed() ? "Bases are reverse-complemented to follow the reference. Alignment-column numbers run backward; genomic coordinates stay native." : "Bases follow alignment orientation. Hover a base for its genomic coordinate.";
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
    // Share handlers across the row instead of allocating two closures per base.
    row.onclick = event => {
      const base = event.target.closest(".base");
      if (base) selectColumn(Number(base.dataset.column));
    };
    row.onkeydown = event => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      const base = event.target.closest(".base");
      if (!base) return;
      event.preventDefault();
      const i = Number(base.dataset.column);
      const next = indices[indices.indexOf(i) + (event.key === "ArrowLeft" ? -1 : 1)];
      if (next === undefined) return;
      selectColumn(next);
      row.querySelector(`[data-column="${next}"]`).focus();
    };
    const label = document.createElement("span"); label.className = "base-label";
    const name = document.createElement("strong");
    name.textContent = state.alignment.genomes.find(g => g.id === m.genome_id).name;
    name.title = name.textContent;
    name.dataset.short = `#${m.genome_id}`;
    const range = document.createElement("small");
    range.textContent = `${fmt(m.start)}–${fmt(m.end)} (${m.strand})${trackDirection(m.genome_id) === -1 ? " · Reversed view" : ""}`;
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
      base.textContent = displayBase(m.bases[i]);
      base.setAttribute("aria-pressed", "false");
      base.tabIndex = -1;
      base.dataset.column = i;
      base.dataset.genome = m.genome_id;
      base.title = `${name.textContent} · Column ${b.offset + i + 1} · ${m.positions[i] === null ? "gap" : `genomic position ${fmt(m.positions[i])}`}`;
      base.setAttribute("aria-label", base.title + ` · ${displayBase(m.bases[i])}`);
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
  $("bases").querySelectorAll(`.base.active-column, .base[data-column="${index}"]`).forEach(base => {
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
    label.textContent = `${name}: ${displayBase(m.bases[index])} · ${position === null ? "gap, no genomic coordinate" : fmt(position) + " bp (" + m.strand + ")"}`;
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
        const view = nearestTrackPosition(position, m.genome_id);
        setRange(view - 100, view + 100, false);
        $("tracks").scrollIntoView({behavior: "smooth", block: "center"});
      };
      row.append(focus);
    }
    records.append(row);
  }
  detail.append(records);
}
function trackOffset(gid) {
  return $("align-tracks").checked ? (state.trackOffsets.get(gid) || 0) : 0;
}
function trackDirection(gid) {
  return $("orient-tracks").checked && $("align-tracks").checked ? (state.trackDirections.get(gid) || 1) : 1;
}
function chromosomeExtent(gid) {
  return state.sources.find(s => s.genome_id === gid)?.metadata.records.at(-1)?.end
    || state.alignment.genomes.find(g => g.id === gid)?.extent || 0;
}
function orientedBase(p, gid, direction = trackDirection(gid)) {
  return window.mauveTrackGeometry.base(p, chromosomeExtent(gid), direction);
}
function orientedEdge(p, gid) {
  return window.mauveTrackGeometry.edge(p, chromosomeExtent(gid), trackDirection(gid));
}
function orientedInterval(start, end, gid) {
  return window.mauveTrackGeometry.interval(start, end, chromosomeExtent(gid), trackDirection(gid));
}
function nativeWindow(gid, copy = 0) {
  const a = orientedBase(state.start + trackOffset(gid) - copy, gid);
  const b = orientedBase(trackEnd(gid) + trackOffset(gid) - copy, gid);
  return [Math.min(a,b), Math.max(a,b)];
}
function displayedStrand(strand, gid) { return (strand === "+" ? 1 : -1) * trackDirection(gid); }
// Only a single annotated circular chromosome has a trustworthy wrap length.
// Alignment extent alone may omit terminal unaligned sequence.
function circularLength(gid) {
  if (!$("align-tracks").checked) return 0;
  const records = state.sources.find(source => source.genome_id === gid)?.metadata.records;
  return records?.length === 1 && records[0].topology === "circular" && records[0].start === 1
    ? records[0].end : 0;
}
function nativePosition(position, gid) {
  const length = circularLength(gid);
  return length ? ((position - 1) % length + length) % length + 1 : position;
}
function trackEnd(gid) {
  const length = circularLength(gid);
  return length ? Math.min(state.end, state.start + length - 1) : state.end;
}
function genomeClip(gid) { return `url(#genome-clip-${gid})`; }
function trackCopies(start, end, gid) {
  return window.mauveTrackGeometry.copies(start, end, {
    extent: chromosomeExtent(gid), direction: trackDirection(gid), offset: trackOffset(gid),
    length: circularLength(gid), viewStart: state.start, viewEnd: state.end,
  });
}
function trackVisible(start, end, gid) {
  return trackCopies(start, end, gid).length > 0;
}
function nearestTrackPosition(position, gid) {
  const length = circularLength(gid), base = orientedBase(position, gid) - trackOffset(gid);
  return length ? base + Math.round(((state.start + trackEnd(gid)) / 2 - base) / length) * length : base;
}
async function alignTracks(detail, location) {
  const aid = state.alignment.id, token = state.detailEpoch, revision = state.mapRevision;
  const current = () => aid === state.alignment?.id && token === state.detailEpoch
    && revision === state.mapRevision && $("align-tracks").checked;
  const candidates = detail.members.filter(m => m.positions.some(p => p !== null));
  const anchor = candidates.find(m => m.genome_id === location?.genome_id)
    || candidates.find(m => m.genome_id === state.reference) || candidates[0];
  if (!anchor) return current();
  const column = anchor.positions.findIndex(p => p !== null);
  if (column < 0) return current();
  const anchorPosition = anchor.positions[column];
  const screenPosition = location?.viewPosition ?? nearestTrackPosition(anchorPosition, anchor.genome_id);
  const directions = window.mauveTrackGeometry.directions(detail.members, state.reference, $("orient-tracks").checked);
  const offsets = new Map(), unresolved = new Set(detail.members.map(m => m.genome_id));
  const resolve = page => {
    const ref = page.members.find(m => m.genome_id === anchor.genome_id);
    if (!ref) return;
    const columns = ref.positions.map((p, i) => i).filter(i => ref.positions[i] !== null)
      .sort((a,b) => Math.abs(page.offset + a - detail.offset - column) - Math.abs(page.offset + b - detail.offset - column));
    for (const member of page.members) {
      if (!unresolved.has(member.genome_id)) continue;
      const index = columns.find(i => member.positions[i] !== null);
      if (index === undefined) continue;
      offsets.set(member.genome_id, orientedBase(member.positions[index], member.genome_id, directions.get(member.genome_id))
        - (screenPosition + directions.get(anchor.genome_id) * (ref.positions[index] - anchorPosition)));
      unresolved.delete(member.genome_id);
    }
  };
  resolve(detail);
  // A clicked insertion can span an entire sequence page. Search outward for
  // actual shared columns; never infer correspondence from block lengths.
  let left = detail.offset, right = detail.offset + anchor.positions.length;
  while (unresolved.size && (left > 0 || right < detail.columns)) {
    const requests = [];
    if (left > 0) {
      const limit = Math.min(500, left); left -= limit;
      requests.push(api(`/api/alignments/${aid}/blocks/${detail.id}?offset=${left}&limit=${limit}`));
    }
    if (right < detail.columns) {
      const limit = Math.min(500, detail.columns - right);
      requests.push(api(`/api/alignments/${aid}/blocks/${detail.id}?offset=${right}&limit=${limit}`)); right += limit;
    }
    const pages = await Promise.all(requests);
    if (!current()) return false;
    for (const page of pages) resolve(page);
  }
  if (!current()) return false;
  for (const [gid, offset] of offsets) {
    state.trackOffsets.set(gid, offset);
    state.trackDirections.set(gid, directions.get(gid));
  }
  return true;
}
function selectOverviewBlock(event, member, id, svg, copy = null) {
  if (!$("align-tracks").checked) return selectBlock(id);
  const point = svg.createSVGPoint(); point.x = event.clientX || 0; point.y = event.clientY || 0;
  const local = event.type === "keydown" ? null : point.matrixTransform(svg.getScreenCTM().inverse());
  const left = 180, right = svg.viewBox.baseVal.width - 26;
  const viewPosition = local ? state.start + (local.x - left) / (right - left) * (state.end - state.start + 1)
    : copy === null ? nearestTrackPosition(member.start, member.genome_id)
      : Math.max(state.start, orientedInterval(member.start, member.end, member.genome_id)[0] + copy - trackOffset(member.genome_id));
  const raw = viewPosition + trackOffset(member.genome_id);
  if (copy === null) {
    const length = circularLength(member.genome_id);
    copy = length ? Math.round((raw - orientedBase((member.start + member.end) / 2, member.genome_id)) / length) * length : 0;
  }
  // Pixels represent base intervals [p, p + 1), not rounded base centers.
  const position = Math.max(member.start, Math.min(member.end, orientedBase(Math.floor(raw - copy + 1e-7), member.genome_id)));
  return selectBlock(id, 0, {genome_id: member.genome_id, position,
    viewPosition: orientedBase(position, member.genome_id) + copy - trackOffset(member.genome_id)}, false, true);
}
function drawIdentity(svg, project, ys, blocks) {
  if (!state.profile || !$("show-identity").checked || !blocks.some(b => b.id === state.selected)) return;
  const layer = svgNode("g", {"clip-path": "url(#track-clip)", class: "identity-layer"});
  svg.append(layer);
  const selectCurrent = safely(() => selectBlock(state.selected, state.offset));
  for (const m of state.profile.members) {
    if (!ys.has(m.genome_id)) continue;
    const baseline = ys.get(m.genome_id) + 18;
    for (const w of m.windows) for (const copy of trackCopies(w.start, w.end, m.genome_id)) {
      const x = p => project(p, m.genome_id, copy);
      const rect = svgNode("rect", {
        x: Math.min(x(w.start), x(w.end + 1)), y: baseline - (w.identity === null ? 18 : w.identity * 18),
        width: Math.max(.5, Math.abs(x(w.end + 1) - x(w.start))),
        height: w.identity === null ? 18 : Math.max(.6, w.identity * 18),
        fill: w.identity === null ? "var(--muted)" : "var(--text)",
        opacity: w.identity === null ? .35 : .65,
        class: "identity-window",
        "clip-path": genomeClip(m.genome_id),
        "data-genome": m.genome_id,
        "data-block-id": state.selected,
      });
      rect.append(svgNode("title", {}, `${fmt(w.start)}–${fmt(w.end)} · ${w.identity === null ? "No comparable bases" : (w.identity * 100).toFixed(1) + "% identity"} · ${w.compared}/${w.columns} comparable columns`));
      rect.onclick = safely(event => {
        const member = state.blocks.find(b => b.id === state.selected)?.members.find(item => item.genome_id === m.genome_id);
        return $("align-tracks").checked && member ? selectOverviewBlock(event, member, state.selected, svg, copy) : selectCurrent();
      });
      layer.append(rect);
    }
  }
}
// Block-member metadata is immutable after loading. Weak keys release cached
// bounds when an alignment is discarded; replacing the members array refreshes it.
const blockBounds = new WeakMap();
function blockIntersectsViewport(block, padding = 0) {
  if ($("align-tracks").checked) return true;
  let bounds = blockBounds.get(block.members);
  if (!bounds) {
    let start = Infinity, end = -Infinity;
    for (const member of block.members) {
      start = Math.min(start, member.start); end = Math.max(end, member.end);
    }
    bounds = [start, end]; blockBounds.set(block.members, bounds);
  }
  return bounds[1] + padding >= state.start && bounds[0] <= state.end + padding;
}
function render() {
  if (!state.alignment) return;
  window.mauveRankCorrelations?.refresh();
  const width = Math.max(660, $("tracks").clientWidth - 24),
    left = 180,
    right = width - 26,
    top = 55,
    gap = $("show-annotations").checked && state.sources.length ? 152 : 112;
  const genomes = visibleGenomes(), blocks = visibleBlocks(), showLinks = $("links").checked;
  const viewportBlocks = blocks.filter(b => blockIntersectsViewport(b, showLinks ? 1 : 0));
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
    x = (p, gid, copy = 0) => left + ((orientedEdge(p, gid) + copy - trackOffset(gid) - state.start) / span) * (right - left),
    ys = new Map();
  genomes.forEach((g, i) => ys.set(g.id, top + i * gap));
  for (const g of genomes) {
    const clip = svgNode("clipPath", {id: `genome-clip-${g.id}`});
    clip.append(svgNode("rect", {x: left, y: 0,
      width: (trackEnd(g.id) - state.start + 1) / span * (right - left), height}));
    defs.append(clip);
  }
  const connections = svgNode("g", { "clip-path": "url(#track-clip)", class: "alignment-links" });
  svg.append(connections);
  if (showLinks)
    for (const b of viewportBlocks) {
      const ms = b.members.filter(m => ys.has(m.genome_id)).sort(
        (a, c) => ys.get(a.genome_id) - ys.get(c.genome_id),
      );
      for (let i = 1; i < ms.length; i++) {
        const a = ms[i - 1],
          c = ms[i];
        const pairs = new Map();
        const addPair = (ac, cc) => pairs.set(`${ac}:${cc}`, [ac, cc]);
        if (!circularLength(a.genome_id) && !circularLength(c.genome_id)) addPair(0, 0);
        else {
          // Both sides of the viewing cut may match the same unsplit member.
          // Intersect their alignment fractions below instead of picking only
          // the geometrically nearest copy.
          for (const ac of trackCopies(a.start, a.end, a.genome_id))
            for (const cc of trackCopies(c.start, c.end, c.genome_id)) addPair(ac, cc);
        }
        for (const [ac, cc] of pairs.values()) {
        const ab = orientedInterval(a.start,a.end,a.genome_id), cb = orientedInterval(c.start,c.end,c.genome_id);
        if (Math.max(ab[1]+ac+1-trackOffset(a.genome_id),cb[1]+cc+1-trackOffset(c.genome_id)) < state.start ||
            Math.min(ab[0]+ac-trackOffset(a.genome_id),cb[0]+cc-trackOffset(c.genome_id)) > state.end+1) continue;
        const interval = (m, copy) => {
          const start = orientedInterval(m.start, m.end, m.genome_id)[0] + copy - trackOffset(m.genome_id), size = m.end - m.start + 1;
          const low = Math.max(0, (state.start - start) / size);
          const high = Math.min(1, (trackEnd(m.genome_id) + 1 - start) / size);
          return displayedStrand(m.strand, m.genome_id) === 1 ? [low, high] : [1 - high, 1 - low];
        };
        const circular = circularLength(a.genome_id) || circularLength(c.genome_id);
        const ai = interval(a, ac), ci = interval(c, cc);
        const low = circular ? Math.max(ai[0], ci[0]) : 0;
        const high = circular ? Math.min(ai[1], ci[1]) : 1;
        if (low >= high) continue;
        const ends = (m, copy) => {
          const at = fraction => x(m.start + (m.strand === "+" ? fraction : 1 - fraction) * (m.end - m.start + 1), m.genome_id, copy);
          return [at(low), at(high)];
        };
        const [a1, a2] = ends(a, ac),
          [c1, c2] = ends(c, cc),
          y1 = ys.get(a.genome_id) + 18,
          y2 = ys.get(c.genome_id);
        connections.append(
          svgNode("path", {
            "data-block-id": b.id,
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
        `#${g.id}${g.id === state.reference ? " · REF" : ""} · ${fmt(g.extent)} bp`,
      ),
    );
    if ($("track-sort").value !== "manual") {
      const distance = trackDistance(g.id);
      const label = g.id === state.reference ? "Distance: 0 · reference" : distance === null ? "Distance: unavailable"
        : `DCJ distance: ${fmt(distance)}`;
      svg.append(svgNode("text", {x:10,y:y+90,class:"tick track-distance","data-genome":g.id},label));
    }
    if (trackDirection(g.id) === -1) svg.append(svgNode("text", {
      x:10, y:y+74, class:"tick reversed-view", "data-genome":g.id
    }, "← Reversed view"));
    if ($("show-identity").checked && blocks.some(b => b.id === state.selected)) {
      const identity = selectedBlockIdentity(g.id);
      const metric = svgNode("g", {class: "block-identity", "data-genome": g.id, "aria-label": identity.title});
      metric.append(svgNode("title", {}, identity.title),
        svgNode("text", {x: 10, y: y + 43, class: "block-identity-value"}, identity.value),
        svgNode("text", {x: 10, y: y + 57, class: "tick"}, identity.detail));
      svg.append(metric);
    }
    svg.append(
      svgNode("line", {
        x1: left,
        x2: left + (trackEnd(g.id) - state.start + 1) / span * (right - left),
        y1: y + 9,
        y2: y + 9,
        stroke: "var(--track-line)",
        "stroke-width": 2,
      }),
    );
    if (circularLength(g.id)) for (const copy of trackCopies(1, 1, g.id)) {
      const origin = svgNode("line", {x1: x(1, g.id, copy), x2: x(1, g.id, copy),
        y1: y - 8, y2: y + 22, stroke: "var(--text)", "stroke-dasharray": "3 3",
        class: "chromosome-origin", "data-genome": g.id});
      origin.append(svgNode("title", {}, "Circular chromosome origin: last base → base 1"));
      svg.append(origin, svgNode("text", {x: x(1, g.id, copy) + 3, y: y - 10, class: "tick origin-label"}, "1 ↻"));
    }
    for (let t = 0; t <= 4; t++) {
      const p = Math.round(state.start + trackOffset(g.id) + ((trackEnd(g.id) - state.start) * t) / 4),
        tx = left + ((p - trackOffset(g.id) - state.start) / span) * (right - left);
      svg.append(
        svgNode(
          "text",
          {
            x: tx,
            y: y + 41,
            class: "tick genome-coordinate",
            "data-genome": g.id,
            "text-anchor": t === 4 ? "end" : "start",
          },
          fmt(nativePosition(orientedBase(p, g.id), g.id)),
        ),
      );
    }
  }
  const rectangles = svgNode("g", { "clip-path": "url(#track-clip)" });
  rectangles.onclick = rectangles.onkeydown = safely(event => {
    if (event.type === "keydown" && event.key !== "Enter" && event.key !== " ") return;
    const target = event.target.closest(".block");
    if (!target) return;
    if (event.type === "keydown") event.preventDefault();
    return selectOverviewBlock(event, target.mauveMember, target.mauveBlockId, svg, target.mauveCopy);
  });
  rectangles.ondblclick = safely(async event => {
    const target = event.target.closest(".block");
    if (!target) return;
    // Finish the new selection before zooming; zooming the previous selection
    // would start a competing sequence request and cancel this alignment.
    const id = target.mauveBlockId;
    const pending = selectOverviewBlock(event, target.mauveMember, id, svg, target.mauveCopy);
    const token = state.detailEpoch, revision = state.mapRevision;
    await pending;
    if (token !== state.detailEpoch || revision !== state.mapRevision || state.selected !== id) return;
    $("zoom-selected").click();
  });
  svg.append(rectangles);
  for (const b of viewportBlocks)
    for (const m of b.members) for (const copy of trackCopies(m.start, m.end, m.genome_id)) {
      if (!ys.has(m.genome_id)) continue;
      const y = ys.get(m.genome_id),
        attrs = {
          x: Math.min(x(m.start, m.genome_id, copy), x(m.end + 1, m.genome_id, copy)),
          y,
          width: Math.max(2, Math.abs(x(m.end + 1, m.genome_id) - x(m.start, m.genome_id))),
          height: 18,
          "clip-path": genomeClip(m.genome_id),
          rx: 3,
        };
      const r = svgNode("rect", {
        ...attrs,
        fill: color(b.id),
        class: "block",
        "data-block-id": b.id,
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
          `Block ${b.id} · ${fmt(m.start)}–${fmt(m.end)} · ${m.strand}${b.id === state.selected ? ` · ${selectedBlockIdentity(m.genome_id).title}` : ''}`,
        ),
      );
      // JS-only metadata keeps exported SVG markup unchanged.
      r.mauveBlockId = b.id; r.mauveMember = m; r.mauveCopy = copy;
      rectangles.append(r);
      if (displayedStrand(m.strand, m.genome_id) === -1)
        rectangles.append(
          svgNode("rect", {
            ...attrs,
            fill: "url(#reverse-hatch)",
            "pointer-events": "none",
          }),
        );
    }
  drawIdentity(svg, x, ys, blocks);
  if (state.detail?.id === state.selected && blocks.some(b => b.id === state.selected)) {
    const layer = svgNode("g", {"clip-path": "url(#track-clip)", class: "sequence-page-markers"});
    for (const member of sequenceMembers()) {
      const positions = member.positions.filter(p => p !== null);
      if (!positions.length || !ys.has(member.genome_id)) continue;
      const start = Math.min(...positions), end = Math.max(...positions);
      for (const copy of trackCopies(start, end, member.genome_id)) {
      const marker = svgNode("rect", {x: Math.min(x(start, member.genome_id, copy), x(end + 1, member.genome_id, copy)), y: ys.get(member.genome_id) + 23,
        width: Math.max(3, Math.abs(x(end + 1, member.genome_id) - x(start, member.genome_id))), height: 4, fill: "var(--purple)", class: "page-window", "clip-path": genomeClip(member.genome_id)});
      marker.append(svgNode("title", {}, `Sequence page: ${fmt(start)}–${fmt(end)} bp · alignment columns ${fmt(state.offset + 1)}–${fmt(state.offset + member.bases.length)}`));
      layer.append(marker);
      }
    }
    svg.append(layer);
  }
  drawAnnotations(svg, x, ys);
  // Highlight corresponding members without changing selection or re-rendering
  // the SVG under the pointer. Identity overlays share their block's hover target.
  const blockId = node => node?.closest?.("[data-block-id]")?.dataset.blockId;
  const highlight = id => {
    for (const node of svg.querySelectorAll("[data-block-id]"))
      node.classList.toggle("block-match-hover", Boolean(id) && node.dataset.blockId === id);
  };
  let hoveredId = null, focusedId = null;
  svg.onpointerover = event => { hoveredId = blockId(event.target); highlight(hoveredId || focusedId); };
  svg.onpointerout = event => { hoveredId = blockId(event.relatedTarget); highlight(hoveredId || focusedId); };
  svg.onpointerleave = () => { hoveredId = null; highlight(focusedId); };
  svg.addEventListener("focusin", event => { focusedId = blockId(event.target); highlight(focusedId || hoveredId); });
  svg.addEventListener("focusout", event => { focusedId = blockId(event.relatedTarget); highlight(hoveredId || focusedId); });
  $("tracks").replaceChildren(svg);
  const aligned = $("align-tracks").checked, gid = state.reference;
  const rangeStart = aligned ? nativePosition(orientedBase(state.start + trackOffset(gid), gid), gid) : state.start;
  const rangeEnd = aligned ? nativePosition(orientedBase(trackEnd(gid) + trackOffset(gid), gid), gid) : state.end;
  const length = circularLength(gid), windowSpan = state.end - state.start + 1;
  const crossesOrigin = length && Math.floor((state.start + trackOffset(gid) - 1) / length) !== Math.floor((trackEnd(gid) + trackOffset(gid) - 1) / length);
  $("range").textContent = `${aligned ? `REF #${gid} · ` : ''}${fmt(rangeStart)}–${fmt(rangeEnd)} bp${crossesOrigin ? ' · crosses origin' : ''}${length && windowSpan > length ? ` · one complete turn` : ''}`;
  $("region").value = `${rangeStart}-${rangeEnd}`;
  $("region").title = aligned ? `Native coordinates in reference genome #${gid}. For circular chromosomes, an end smaller than the start crosses the origin.` : "Genomic coordinate range";
  updateMapFeedback();
}
function setRange(start, end, sync = true) {
  ++state.mapRevision;
  const span = Math.min(state.max, Math.max(1, Math.round(end - start + 1)));
  const wraps = state.alignment.genomes.some(g => circularLength(g.id));
  state.start = wraps ? Math.round(start) : Math.max(1, Math.min(state.max - span + 1, Math.round(start)));
  state.end = state.start + span - 1;
  render();
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
  const matchingGenomes = query ? new Set(state.alignment.genomes
    .filter(g => g.name.toLowerCase().includes(query)).map(g => g.id)) : null;
  const blocks = visibleBlocks().filter(b => !query || String(b.id) === query
    || `block ${b.id}`.includes(query)
    || b.members.some(m => matchingGenomes.has(m.genome_id)));
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
    button.onclick = safely(() => selectBlock(b.id, null, null, false, true));
    $("block-list").append(button);
  }
}
async function selectBlock(id, offset = null, location = null, followPage = false, alignClick = false) {
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
  const changedBlock = state.selected !== id;
  if ($("align-tracks").checked && (changedBlock || alignClick) && !await alignTracks(b, location)) return;
  if (token !== state.detailEpoch || aid !== state.alignment?.id) return;
  state.selected = id;
  $("export-fasta").hidden = false;
  $("export-fasta").href = `/api/alignments/${aid}/blocks/${id}/fasta`;
  $("selection-status").textContent = `Block ${id} · ${fmt(b.columns)} columns`;
  $("jump-sequence").disabled = false;
  $("zoom-selected").disabled = false;
  if (changedBlock) { loadProfile(); safely(loadFeatures)(); }
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
  notice("Opening the eight-strain E. coli demo and its annotations…");
  $("demo").disabled = $("welcome-demo").disabled = true;
  try {
    const a = await api("/api/demo", { method: "POST" });
    await openAlignment(a.id);
  } finally { $("demo").disabled = $("welcome-demo").disabled = false; }
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
  const members = block.members.filter(m => !state.hidden.has(m.genome_id) && trackVisible(m.start, m.end, m.genome_id));
  const member = members.find(m => m.genome_id === state.reference) || members[0];
  if (!member) return null;
  const copy = trackCopies(member.start, member.end, member.genome_id)[0];
  const [start,end] = nativeWindow(member.genome_id,copy);
  return {genome_id: member.genome_id, position: member.strand === "+"
    ? Math.max(member.start,start) : Math.min(member.end,end)};
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
  const center = nearestTrackPosition((start+end)/2,member.genome_id);
  setRange(center-(end-start)/2-20,center+(end-start)/2+20,false);
}
function clearBlockFilters(preserveCore = false) {
  if (!preserveCore) $("core-genes-only").checked = false;
  updateCoreGeneStatus();
  $("min-columns").value = 0;
  $("shared-only").checked = $("isolate-block").checked = false;
  $("block-search").value = "";
}
function revealSelected() {
  const block = state.blocks.find(b => b.id === state.selected);
  if (!block) return;
  clearBlockFilters(coreBlockIds.has(block.id));
  for (const member of block.members) state.hidden.delete(member.genome_id);
  refreshTracks(); renderList();
  const intervals = block.members.map(m => {
    const center = nearestTrackPosition((m.start+m.end)/2,m.genome_id);
    return [center-(m.end-m.start)/2,center+(m.end-m.start)/2];
  });
  const start = Math.min(...intervals.map(p=>p[0]));
  const end = Math.max(...intervals.map(p=>p[1]));
  setRange(start, end);
}
function updateMapFeedback() {
  const blocks = visibleBlocks();
  const hasMembers = blocks.some(b => b.members.some(m => !state.hidden.has(m.genome_id)));
  const inRegion = blocks.some(b => b.members.some(m => !state.hidden.has(m.genome_id) && trackVisible(m.start, m.end, m.genome_id)));
  $("map-feedback").hidden = inRegion;
  $("map-feedback-text").textContent = !blocks.length ? "No blocks match these filters. Fit all changes the coordinate range, not filters."
    : !hasMembers ? "All genomes containing these blocks are hidden." : "No blocks are visible in this coordinate range.";
  $("clear-map-filters").textContent = !blocks.length ? "Clear filters" : !hasMembers ? "Show all genomes" : "Fit all";
  $("clear-map-filters").dataset.action = !blocks.length ? "filters" : !hasMembers ? "tracks" : "range";
  const corePending = $("core-genes-only").checked && !window.mauveGeneAnalysis?.result;
  $("clear-map-filters").disabled = false;
  $("tracks").setAttribute("aria-busy", String(corePending && $("run-gene-analysis").disabled));
  if (corePending) {
    $("map-feedback").hidden = false;
    $("map-feedback-text").textContent = `Core-family filter pending — showing all blocks. ${window.mauveGeneAnalysis?.status || "Compute gene comparisons to apply the filter."}`;
    $("clear-map-filters").textContent = $("run-gene-analysis").disabled ? "Computing core families…" : "Compute gene comparisons";
    $("clear-map-filters").dataset.action = "analysis";
    $("clear-map-filters").disabled = $("run-gene-analysis").disabled;
  }
  if (!corePending && $("core-genes-only").checked && !blocks.length) {
    $("map-feedback-text").textContent = coreBlockIds.size
      ? `${fmt(coreBlockIds.size)} blocks contain core-family genes, but other display filters hide them.`
      : "No blocks contain core-family genes under the current gene-matching rules.";
    if (coreBlockIds.size) {
      $("clear-map-filters").textContent = "Show core blocks";
      $("clear-map-filters").dataset.action = "core-blocks";
    }
  }
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
  if (action === "core-blocks") {
    clearBlockFilters();
    $("core-genes-only").checked = true;
    refreshCoreGenes(); renderList();
  }
  else if (action === "analysis") $("run-gene-analysis").click();
  else if (action === "filters") { clearBlockFilters(); render(); renderList(); }
  else if (action === "tracks") { state.hidden.clear(); refreshTracks(); }
  else fitAllTracks();
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
  $("core-genes-only").checked = false; updateCoreGeneStatus();
  $("align-tracks").checked = false;
  $("orient-tracks").checked = false;
  $("track-sort").value = "manual"; applyTrackOrder();
  state.trackDirections.clear();
  state.trackOffsets.clear();
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
  const sections = ["overview-panel", "gene-analysis-panel", "sequence-panel", "annotations-panel"];
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
$("reference-genome").onchange = safely(async () => {
  state.reference = Number($("reference-genome").value);
  ++state.detailEpoch;
  applyTrackOrder(); renderTrackControls();
  if ($("orient-tracks").checked && state.detail) await alignTracks(state.detail);
  loadProfile();
});
$("show-identity").onchange = loadProfile;
$("focus-reference").onclick = () => {
  const member = state.blocks.find(b => b.id === state.selected)?.members.find(m => m.genome_id === state.reference);
  if (!member) return;
  state.hidden.delete(state.reference);
  renderTrackControls();
  const margin = Math.max(10, (member.end - member.start) * .1);
  const center = nearestTrackPosition((member.start+member.end)/2,member.genome_id);
  setRange(center-(member.end-member.start)/2-margin,center+(member.end-member.start)/2+margin);
};
$("zoom-in").onclick = () => zoom(0.5);
$("zoom-out").onclick = () => zoom(2);
function fitAllTracks() {
  state.trackOffsets.clear();
  setRange(1, state.max, false);
}
$("zoom-selected").onclick = () => {
  const block = state.blocks.find(b => b.id === state.selected);
  if (!block) return;
  clearBlockFilters(coreBlockIds.has(block.id));
  const aligned = $("align-tracks").checked;
  const reference = block.members.find(m => m.genome_id === state.reference) || block.members[0];
  const members = aligned ? block.members : [reference];
  for (const member of members) state.hidden.delete(member.genome_id);
  renderTrackControls(); renderList();
  const intervals = members.map(m => {
    const midpoint = (m.start + m.end) / 2;
    const center = nearestTrackPosition(midpoint, m.genome_id);
    return [center - (midpoint - m.start), center + (m.end - midpoint)];
  });
  const start = Math.min(...intervals.map(p => p[0]));
  const end = Math.max(...intervals.map(p => p[1]));
  const margin = Math.max(10, (end - start + 1) * .08);
  setRange(start - margin, end + margin);
};
$("reset").onclick = fitAllTracks;
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
    .match(/^\s*(-?\d+)\s*[-–:]\s*(-?\d+)\s*$/);
  const aligned = $("align-tracks").checked, gid = state.reference;
  const length = circularLength(gid);
  const limit = aligned ? (length || state.alignment.genomes.find(g => g.id === gid).extent) : state.max;
  if (!m || +m[1] < 1 || +m[2] < 1 || +m[1] > limit || +m[2] > limit || (!length && +m[2] < +m[1])) {
    notice(`Enter native coordinates between 1 and ${fmt(limit)}${length ? '; an end smaller than the start crosses the origin' : ''}.`, true);
    return;
  }
  notice("");
  const start = +m[1], end = +m[2];
  const viewStart = aligned ? nearestTrackPosition(start, gid) : start;
  const distance = end >= start ? end - start : length - start + end;
  setRange(viewStart, viewStart + distance);
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
  const block = state.blocks.find(b => b.id === state.selected);
  state.features = [];
  $("feature-limit").hidden = false;
  $("feature-limit").textContent = block ? `Loading annotations for block ${block.id}…` : "Select a block to show its gene annotations.";
  render();
  if (!block) return;
  const current = () => token === state.featureEpoch && aid === state.alignment?.id && block.id === state.selected;
  const members = block.members.filter(m => state.sources.some(s => s.genome_id === m.genome_id));
  try {
    const results = await Promise.all(members.map(async member => {
      const features = [];
      for (let offset = 0; current(); offset += 500) {
        const params = new URLSearchParams({genome_id: member.genome_id, start: member.start, end: member.end, limit: 500, offset});
        const result = await api(`/api/alignments/${aid}/features?${params}`);
        if (!current()) return [];
        // A compound feature's bounding span can overlap a block even when
        // none of its annotated segments does (e.g. an origin-spanning gene).
        features.push(...result.items.filter(f => f.parts.some(p => p.start <= member.end && p.end >= member.start)));
        if (offset + result.items.length >= result.total || !result.items.length) break;
      }
      return features;
    }));
    if (!current()) return;
    state.features = results.flat();
    const missing = block.members.length - members.length;
    $("feature-limit").textContent = `Block ${block.id} · ${fmt(state.features.length)} overlapping annotation features across ${members.length} annotated genome(s). Arrows are clipped to each genome’s block interval.${missing ? ` ${missing} block member(s) have no imported annotations.` : ''}`;
    render();
  } catch (error) {
    if (!current()) return;
    $("feature-limit").textContent = `Block ${block.id} annotations unavailable: ${error.message}`;
    throw error;
  }
}
function drawAnnotations(svg, project, ys) {
  if (!$("show-annotations").checked) return;
  const block = visibleBlocks().find(b => b.id === state.selected);
  if (!block) return;
  const members = new Map(block.members.map(m => [m.genome_id, m]));
  const layer = svgNode("g", { "clip-path": "url(#track-clip)" });
  svg.append(layer);
  for (const source of state.sources) {
    if (!ys.has(source.genome_id)) continue;
    const y = ys.get(source.genome_id);
    for (const record of source.metadata.records) for (const copy of trackCopies(record.start, record.start, source.genome_id)) {
      const x = p => project(p, source.genome_id, copy);
      const boundary = svgNode("line", {
        "clip-path": genomeClip(source.genome_id),
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
    if ($("core-genes-only").checked && !coreGeneKeys.has(`${f.genome_id}:${f.id}`)) continue;
    const member = members.get(f.genome_id);
    if (!ys.has(f.genome_id) || !member) continue;
    const parts = f.parts.filter(p => p.start <= member.end && p.end >= member.start);
    if (!parts.some(p => trackVisible(Math.max(p.start, member.start), Math.min(p.end, member.end), f.genome_id))) continue;
    const start = Math.max(f.start, member.start), end = Math.min(f.end, member.end);
    if (!lanes.has(f.genome_id)) lanes.set(f.genome_id, [0, 0, 0]);
    const occupied = lanes.get(f.genome_id);
    let lane = occupied.findIndex(previousEnd => previousEnd < start);
    // Dense features share the last lane; searchable details remain available.
    if (lane < 0) lane = 2;
    occupied[lane] = Math.max(occupied[lane], end);
    const y = ys.get(f.genome_id) + 55 + lane * 17;
    for (const copy of trackCopies(start, end, f.genome_id)) {
    const x = p => project(p, f.genome_id, copy);
    const length = circularLength(f.genome_id);
    const spansOrigin = length && parts.some(p => p.start === 1) && parts.some(p => p.end === length);
    if (parts.length > 1 && !spansOrigin)
      layer.append(
        svgNode("line", {
          "clip-path": genomeClip(f.genome_id),
          x1: x(start),
          x2: x(end + 1),
          y1: y + 5,
          y2: y + 5,
          stroke: "var(--feature-line)",
          "stroke-dasharray": "2 2",
        }),
      );
    for (const part of parts) {
      const [visibleStart,visibleEnd] = nativeWindow(f.genome_id,copy);
      const partStart = Math.max(part.start, member.start, visibleStart);
      const partEnd = Math.min(part.end, member.end, visibleEnd);
      if (partEnd < partStart) continue;
      const a = Math.min(x(partStart),x(partEnd+1)),
        b = Math.min(Math.max(x(member.start),x(member.end+1)), Math.max(a + 3, Math.max(x(partStart),x(partEnd+1)))),
        tip = Math.min(6, (b - a) / 2);
      const points =
        displayedStrand(part.strand,f.genome_id) === 1 && (part.strand === "+" ? part.end <= partEnd : part.start >= partStart)
          ? `${a},${y} ${b - tip},${y} ${b},${y + 5} ${b - tip},${y + 10} ${a},${y + 10}`
          : displayedStrand(part.strand,f.genome_id) === -1 && (part.strand === "+" ? part.end <= partEnd : part.start >= partStart)
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
        "clip-path": genomeClip(f.genome_id),
        "data-genome": f.genome_id,
        "data-feature-id": f.id,
        "data-part-index": f.parts.indexOf(part),
        "data-visible-start": partStart,
        "data-visible-end": partEnd,
        role: "button",
        tabindex: 0,
        "aria-label": `${f.name}, ${f.type}, ${f.start} to ${f.end}`,
      });
      node.append(
        svgNode(
          "title",
          {},
          `${f.name} · ${f.type} · ${fmt(part.start)}–${fmt(part.end)} (${part.strand})${part.fuzzy ? " · approximate boundary" : ""}${part.start < member.start || part.end > member.end ? ` · clipped to block ${block.id}` : ''}${partStart > Math.max(part.start, member.start) || partEnd < Math.min(part.end, member.end) ? ` · visible bases ${fmt(partStart)}–${fmt(partEnd)} (continues beyond this edge)` : ''}`,
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
    const center = nearestTrackPosition((f.start+f.end)/2,f.genome_id);
    setRange(center-(f.end-f.start)/2-margin,center+(f.end-f.start)/2+margin,false);
    const candidates = state.blocks.map(block => {
      const member = block.members.find(m => m.genome_id === f.genome_id);
      const overlap = member ? f.parts.reduce((n, p) => n + Math.max(0, Math.min(p.end, member.end) - Math.max(p.start, member.start) + 1), 0) : 0;
      return {block, overlap};
    }).filter(candidate => candidate.overlap > 0);
    const target = candidates.find(c => c.block.id === state.selected) || candidates.sort((a, b) => b.overlap - a.overlap)[0];
    if (target) {
      const member = target.block.members.find(m => m.genome_id === f.genome_id);
      const part = f.parts.find(p => p.start <= member.end && p.end >= member.start);
      safely(() => selectBlock(target.block.id, 0, {genome_id: f.genome_id, position: Math.max(part.start, member.start)}))();
    } else detail.append(document.createTextNode("This feature is outside the aligned blocks."));
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
$("align-tracks").onchange = safely(async () => {
  ++state.detailEpoch;
  state.trackOffsets.clear();
  if (!$("align-tracks").checked) { $("orient-tracks").checked = false; state.trackDirections.clear(); }
  if ($("align-tracks").checked && state.detail && !await alignTracks(state.detail)) return;
  setRange(state.start, state.end, false);
  renderBases();
});
$("orient-tracks").onchange = safely(async () => {
  ++state.detailEpoch;
  if ($("orient-tracks").checked) $("align-tracks").checked = true;
  if (state.detail && !await alignTracks(state.detail)) return;
  if (!$("orient-tracks").checked) state.trackDirections.clear();
  render(); renderBases();
});
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
    window.mauveGeneAnalysis?.reset();
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
      `Genomic coordinates are 1-based inclusive. Colors denote alignment blocks; hatching denotes reverse strands. Green arrows are GenBank features; selected features are purple. Track percentages show whole-block nucleotide identity for selected block ${state.selected ?? 'none'} versus ${state.alignment.genomes.find(g => g.id === state.reference)?.name}. Dark bars show identity per window (0–100%); gaps and ambiguous bases are excluded. Gray windows have no comparable bases. Purple marks below tracks indicate the current sequence page. Coordinate labels remain native to each genome. ${$("align-tracks").checked ? "Tracks are shifted to align corresponding positions in the selected block; annotated circular chromosomes wrap at their origin." : "Tracks share a coordinate origin."} ${$("orient-tracks").checked ? "Tracks marked Reversed view are displayed in reverse orientation relative to their native coordinates." : ""} ${$("core-genes-only").checked ? "Gene arrows are restricted to core families present in every loaded genome; only blocks overlapping those genes are shown." : ""} This export captures the current visible overview.`,
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
  window.mauveAnalytics?.trackUsage("svg-downloaded");
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

new ResizeObserver(() => render()).observe($("tracks"));
safely(async () => {
  await library();
  if (location.hash.length > 1) await openAlignment(location.hash.slice(1));
})();
