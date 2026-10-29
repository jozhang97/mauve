"use strict";
const ncbiState = {
  selected: new Map(),
  rows: [],
  pages: [""],
  page: 0,
  next: "",
  query: null,
  searching: false,
  downloading: false,
  token: 0,
};
function ncbiError(message) {
  $("ncbi-error").textContent = message;
  $("ncbi-error").hidden = !message;
}
function updateNCBIControls() {
  const busy = ncbiState.searching || ncbiState.downloading;
  $("ncbi-search-button").disabled = busy;
  $("ncbi-previous").disabled = busy || ncbiState.page === 0;
  $("ncbi-next").disabled = busy || !ncbiState.next;
  const chosen = ncbiState.selected.size,
    slots = 8 - jobState.inputs.length;
  $("ncbi-use").disabled =
    busy || jobState.busy || chosen === 0 || chosen > slots;
  $("ncbi-use").textContent = ncbiState.downloading
    ? "Downloading…"
    : `Download ${chosen || "selected"} genome${chosen === 1 ? "" : "s"}`;
  $("ncbi-selection-count").textContent =
    `${chosen} selected · ${slots} slots available in the alignment form`;
  $("ncbi-selected").replaceChildren();
  for (const [accession, row] of ncbiState.selected) {
    const b = document.createElement("button");
    b.textContent = `${accession} ×`;
    b.title = `Remove ${row.organism}`;
    b.disabled = busy;
    b.onclick = () => {
      ncbiState.selected.delete(accession);
      renderNCBIRows();
    };
    $("ncbi-selected").append(b);
  }
  for (const box of $("ncbi-results").querySelectorAll(
    'input[type="checkbox"]',
  )) {
    box.disabled = busy || box.dataset.tooLarge === "true";
  }
}
function renderNCBIRows() {
  $("ncbi-results").replaceChildren();
  for (const row of ncbiState.rows) {
    const tr = document.createElement("tr"),
      select = document.createElement("td"),
      box = document.createElement("input");
    box.type = "checkbox";
    box.setAttribute("aria-label", `Select ${row.accession}`);
    box.checked = ncbiState.selected.has(row.accession);
    box.dataset.tooLarge = String(row.bases > 50 * 1024 * 1024);
    box.disabled = box.dataset.tooLarge === "true";
    box.onchange = () => {
      if (box.checked) {
        if (ncbiState.selected.size + jobState.inputs.length >= 8) {
          box.checked = false;
          ncbiError(
            "At most 8 genomes can be added to an alignment. Remove a selected or staged genome first.",
          );
          return;
        }
        ncbiState.selected.set(row.accession, row);
      } else ncbiState.selected.delete(row.accession);
      ncbiError("");
      updateNCBIControls();
    };
    select.append(box);
    tr.append(select);
    const assembly = document.createElement("td"),
      link = document.createElement("a");
    link.href = row.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = row.accession;
    assembly.append(link);
    function line(parent, text) {
      if (!text) return;
      const div = document.createElement("div");
      div.className = "small";
      div.textContent = text;
      parent.append(div);
    }
    line(assembly, `${row.source} · ${row.name}`);
    line(
      assembly,
      row.paired_accession ? `Paired: ${row.paired_accession}` : "",
    );
    line(assembly, row.reference_category);
    const organism = document.createElement("td");
    organism.textContent = row.organism;
    line(organism, row.strain ? `Strain: ${row.strain}` : "");
    line(organism, `Taxon ${row.taxon_id}`);
    const level = document.createElement("td");
    level.textContent = row.level;
    line(level, row.status);
    line(level, row.release_date);
    const size = document.createElement("td");
    size.textContent = row.bases ? `${fmt(row.bases)} bp` : "Size unavailable";
    line(
      size,
      row.contigs !== null && row.contigs !== undefined
        ? `${fmt(row.contigs)} contigs`
        : "",
    );
    line(size, row.bases > 50 * 1024 * 1024 ? "Exceeds input limit" : "");
    tr.append(assembly, organism, level, size);
    $("ncbi-results").append(tr);
  }
  $("ncbi-table").hidden = ncbiState.rows.length === 0;
  updateNCBIControls();
}
async function loadNCBIPage(page) {
  const token = ++ncbiState.token;
  ncbiState.searching = true;
  ncbiError("");
  updateNCBIControls();
  $("ncbi-status").textContent = "Searching NCBI…";
  try {
    const params = new URLSearchParams({
      ...ncbiState.query,
      page_token: ncbiState.pages[page],
      page_size: 25,
    });
    const data = await api(`/api/ncbi/assemblies?${params}`);
    if (token !== ncbiState.token) return;
    ncbiState.rows = data.assemblies;
    ncbiState.page = page;
    ncbiState.next = data.next_page_token;
    $("ncbi-status").textContent =
      `${data.taxon.name || "Taxon " + data.taxon.id} · ${fmt(data.total)} matching assemblies${data.includes_descendants ? " (including descendant taxa)" : " (exact taxon)"}${data.total === 0 ? ". Try including descendant taxa or changing the database filter. This search covers assembly records, not all viral sequence records." : "."}`;
    $("ncbi-page").textContent =
      `Page ${page + 1} · ${fmt(page * 25 + 1)}–${fmt(page * 25 + data.assemblies.length)} of ${fmt(data.total)}`;
    $("ncbi-pagination").hidden = data.total === 0;
    renderNCBIRows();
  } catch (e) {
    ncbiError(e.message);
    $("ncbi-status").textContent =
      "Search did not complete. You can retry without losing your selected genomes.";
  } finally {
    if (token === ncbiState.token) {
      ncbiState.searching = false;
      updateNCBIControls();
    }
  }
}
$("browse-ncbi").onclick = () => {
  $("ncbi-dialog").showModal();
  updateNCBIControls();
};
$("close-ncbi").onclick = () => $("ncbi-dialog").close();
$("ncbi-search").onsubmit = (e) => {
  e.preventDefault();
  if (ncbiState.searching || ncbiState.downloading) return;
  ncbiState.query = {
    taxon_id: $("ncbi-taxon").value,
    source: $("ncbi-source").value,
    versions: $("ncbi-versions").value,
    exact: $("ncbi-exact").checked,
    q: $("ncbi-query").value.trim(),
  };
  ncbiState.pages = [""];
  ncbiState.page = 0;
  ncbiState.next = "";
  ncbiState.rows = [];
  ncbiState.selected.clear();
  $("ncbi-pagination").hidden = true;
  renderNCBIRows();
  loadNCBIPage(0);
};
$("ncbi-next").onclick = () => {
  if (ncbiState.next) {
    ncbiState.pages[ncbiState.page + 1] = ncbiState.next;
    loadNCBIPage(ncbiState.page + 1);
  }
};
$("ncbi-previous").onclick = () => {
  if (ncbiState.page > 0) loadNCBIPage(ncbiState.page - 1);
};
$("ncbi-use").onclick = async () => {
  if (ncbiState.downloading || jobState.busy) return;
  const chosen = [...ncbiState.selected.values()];
  if (chosen.length + jobState.inputs.length > 8) {
    ncbiError(
      "The selection exceeds 8 genomes. Remove some before downloading.",
    );
    return;
  }
  const total =
    chosen.reduce((n, r) => n + r.bases, 0) +
    jobState.inputs.reduce((n, r) => n + r.bases, 0);
  if (total > 100000000) {
    ncbiError(
      "Selected genomes exceed the current 100 million base limit per alignment.",
    );
    return;
  }
  ncbiState.downloading = true;
  jobState.busy = true;
  ncbiError("");
  updateNCBIControls();
  renderInputs();
  try {
    let i = 0;
    for (const row of chosen) {
      $("ncbi-status").textContent =
        `Downloading ${row.accession} (${++i}/${chosen.length})…`;
      const input = await api(`/api/ncbi/assemblies/${row.accession}/input`, {
        method: "POST",
      });
      jobState.inputs.push(input);
      ncbiState.selected.delete(row.accession);
      renderInputs();
      renderNCBIRows();
    }
    $("ncbi-status").textContent =
      "Genomes downloaded and added to the alignment form.";
    if ($("job-name").value === "New alignment")
      $("job-name").value = `Taxon ${ncbiState.query.taxon_id} alignment`;
    if ($("ncbi-dialog").open) {
      $("ncbi-dialog").close();
      await showAlignmentForm();
    } else
      notice(
        "NCBI genomes are ready. Open Align sequences to review and start the alignment.",
      );
  } catch (e) {
    ncbiError(
      `${e.message} Successfully downloaded genomes remain in the alignment form; retry downloads the remaining selection.`,
    );
  } finally {
    ncbiState.downloading = false;
    jobState.busy = false;
    updateNCBIControls();
    renderInputs();
  }
};
