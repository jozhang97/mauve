"use strict";
const jobState = {
  inputs: [],
  busy: false,
  engine: null,
  selected: null,
  token: 0,
  active: new Set(),
  results: "",
  listToken: 0,
};
function jobFormError(message) {
  $("job-form-error").textContent = message;
  $("job-form-error").hidden = !message;
}
function renderInputs() {
  $("staged-inputs").replaceChildren();
  for (const input of jobState.inputs) {
    const li = document.createElement("li"),
      text = document.createElement("span"),
      remove = document.createElement("button");
    text.textContent = `${input.name}${input.provenance?.organism ? " · " + input.provenance.organism : ""} · ${fmt(input.bases)} bp · ${input.records.length} record(s)`;
    remove.type = "button";
    remove.textContent = "Remove";
    remove.disabled = jobState.busy;
    remove.onclick = () => {
      jobState.inputs = jobState.inputs.filter((i) => i.id !== input.id);
      renderInputs();
    };
    li.append(text, remove);
    $("staged-inputs").append(li);
  }
  $("sequence-files").disabled = jobState.busy;
  $("submit-job").disabled =
    jobState.busy || !jobState.engine?.available || jobState.inputs.length < 2;
  $("submit-job").textContent = jobState.busy
    ? "Preparing…"
    : "Start alignment";
}
async function showAlignmentForm() {
  $("alignment-dialog").showModal();
  jobFormError("");
  $("engine-status").textContent = "Checking progressiveMauve…";
  try {
    jobState.engine = await api("/api/engine");
    $("engine-status").textContent = jobState.engine.available
      ? `Ready · ${jobState.engine.version}`
      : jobState.engine.reason;
    renderInputs();
  } catch (e) {
    jobFormError(e.message);
  }
}
$("new-alignment").onclick = safely(showAlignmentForm);
$("close-alignment-dialog").onclick = () => $("alignment-dialog").close();
$("sequence-files").onchange = async () => {
  const files = [...$("sequence-files").files];
  if (!files.length) return;
  jobFormError("");
  jobState.busy = true;
  renderInputs();
  try {
    if (files.length + jobState.inputs.length > 8)
      throw Error("Choose at most 8 genome files.");
    for (const file of files) {
      if (file.size > 50 * 1024 * 1024)
        throw Error(`${file.name} exceeds the 50 MiB limit.`);
      const input = await api(
        `/api/inputs?name=${encodeURIComponent(file.name)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: file,
        },
      );
      jobState.inputs.push(input);
      renderInputs();
    }
  } catch (e) {
    jobFormError(e.message);
  } finally {
    jobState.busy = false;
    $("sequence-files").value = "";
    renderInputs();
  }
};
$("alignment-form").onsubmit = async (e) => {
  e.preventDefault();
  if (jobState.busy) return;
  jobFormError("");
  jobState.busy = true;
  renderInputs();
  try {
    const weight = $("job-weight").value;
    const job = await api("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: $("job-name").value.trim() || "New alignment",
        input_ids: jobState.inputs.map((i) => i.id),
        collinear: $("job-collinear").checked,
        seed_family: $("job-seed-family").checked,
        concatenate_records: $("job-concatenate").checked,
        min_weight: weight === "" ? null : Number(weight),
      }),
    });
    $("alignment-dialog").close();
    jobState.inputs = [];
    await selectJob(job.id);
    await refreshJobs();
  } catch (e) {
    jobFormError(e.message);
  } finally {
    jobState.busy = false;
    renderInputs();
  }
};
async function selectJob(id) {
  jobState.selected = id;
  $("job-panel").hidden = false;
  $("job-title").textContent = "Loading job…";
  $("job-log").textContent = "";
  $("job-error").hidden = true;
  $("cancel-job").hidden = true;
  $("open-result").hidden = true;
  $("rerun-job").hidden = true;
  $("job-artifacts").replaceChildren();
  $("job-status").textContent = "";
  $("job-time").textContent = "";
  await refreshJobDetail();
  $("job-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}
async function refreshJobDetail() {
  const id = jobState.selected;
  if (!id) return;
  const token = ++jobState.token;
  const job = await api(`/api/jobs/${id}`);
  if (jobState.selected !== id || token !== jobState.token) return;
  $("job-title").textContent = job.name;
  $("job-status").textContent = job.can_import_result ? "Import failed" : job.status;
  $("job-status").className = `job-badge ${job.status}`;
  $("job-time").textContent =
    `Submitted ${new Date(job.created).toLocaleString()}`;
  $("job-error").hidden = !job.error;
  $("job-error").textContent = job.error || "";
  $("cancel-job").hidden = !["queued", "running", "cancelling"].includes(
    job.status,
  );
  $("cancel-job").disabled = job.status === "cancelling";
  $("cancel-job").textContent =
    job.status === "cancelling" ? "Cancelling…" : "Cancel job";
  $("cancel-job").onclick = safely(async () => {
    await api(`/api/jobs/${id}/cancel`, { method: "POST" });
    await refreshJobs();
  });
  $("rerun-job").hidden = ![
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
  ].includes(job.status);
  $("rerun-job").onclick = safely(async () => {
    $("rerun-job").disabled = true;
    try {
      const next = await api("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...job.spec.options,
          input_ids: job.spec.inputs.map((i) => i.id),
        }),
      });
      await selectJob(next.id);
      await refreshJobs();
    } finally {
      $("rerun-job").disabled = false;
    }
  });
  $("retry-import").hidden = !job.can_import_result;
  $("retry-import").onclick = safely(async () => {
    $("retry-import").disabled = true;
    try {
      await api(`/api/jobs/${id}/import`, {method: "POST"});
      await refreshJobs();
    } finally { $("retry-import").disabled = false; }
  });
  $("open-result").hidden = !job.alignment_id;
  $("open-result").onclick = safely(async () => {
    await openAlignment(job.alignment_id);
    $("job-panel").hidden = true;
    jobState.selected = null;
  });
  const log = $("job-log"),
    atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
  if (log.textContent !== job.log) {
    log.textContent = job.log || "Waiting for aligner output…";
    if (atBottom) log.scrollTop = log.scrollHeight;
  }
  $("log-tail").textContent = job.log_truncated
    ? "(last 32 KiB; download full log below)"
    : "";
  $("job-artifacts").replaceChildren();
  for (const key of job.artifacts) {
    // Partial scientific outputs should not be presented as completed results.
    if (
      job.status !== "succeeded" &&
      !["manifest", "log"].includes(key) &&
      !(job.status === "failed" && key === "xmfa")
    )
      continue;
    const a = document.createElement("a");
    a.className = "download";
    a.href = `/api/jobs/${id}/artifacts/${key}`;
    a.textContent = {
      xmfa:
        job.status === "succeeded"
          ? "XMFA alignment"
          : "Raw XMFA (not validated)",
      tree: "Guide tree",
      backbone: "Backbone",
      log: "Full log",
      manifest: "Parameters & provenance",
    }[key];
    $("job-artifacts").append(a);
  }
}
async function refreshJobs() {
  const token = ++jobState.listToken;
  const jobs = await api("/api/jobs");
  if (token !== jobState.listToken) return;
  const active = new Set(
    jobs
      .filter((j) =>
        ["queued", "running", "cancelling", "importing"].includes(j.status),
      )
      .map((j) => j.id),
  );
  const results = jobs
    .filter((j) => j.alignment_id)
    .map((j) => j.alignment_id)
    .join(",");
  const newlyCompleted = results !== jobState.results;
  jobState.results = results;
  jobState.active = active;
  $("job-library").replaceChildren();
  for (const job of jobs) {
    const b = document.createElement("button");
    b.textContent = `${job.name} · ${job.status}`;
    b.title = b.textContent;
    b.onclick = safely(() => selectJob(job.id));
    $("job-library").append(b);
  }
  if (newlyCompleted) await library();
  await refreshJobDetail();
}
$("close-job").onclick = () => {
  jobState.selected = null;
  ++jobState.token;
  $("job-panel").hidden = true;
};
async function pollJobs() {
  try {
    await refreshJobs();
  } catch (e) {
    if (jobState.selected) {
      $("job-error").textContent = `Could not refresh job: ${e.message}`;
      $("job-error").hidden = false;
    }
  }
  setTimeout(pollJobs, jobState.active.size || jobState.selected ? 1500 : 5000);
}
pollJobs();
