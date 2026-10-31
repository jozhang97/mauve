# Mauve Explorer

A web interface for running progressiveMauve and exploring XMFA/Mauve alignments. The standalone browser build runs on GitHub Pages with no backend. The original Java application remains at the repository root, and the Python server remains available as a reference and for native workloads.

## Standalone browser app / GitHub Pages

From the repository root:

```sh
./web/run-browser.sh
```

Open http://127.0.0.1:8766. Python only serves static files during this local
preview; all parsing, storage, NCBI downloads, alignment jobs, and viewing run
in the browser. There are no Python API requests or CDN dependencies for
computation. The Pages release optionally loads GoatCounter for usage analytics.
The script builds into a temporary directory and removes it when stopped.
Set `MAUVE_BROWSER_PORT` to change the preview port.

The standalone app supports the demo, XMFA imports, GenBank annotations and gene
search, coordinate navigation, identity profiles, FASTA/TSV/SVG exports, NCBI
assembly search/download, and progressiveMauve jobs with logs, cancellation,
rerun, and artifact downloads. NCBI requests go directly to NCBI only when you
use those features. Your uploaded genome data is not sent to a computation
server. Local files, demo viewing and alignment jobs work without NCBI access.
Optional usage analytics send only fixed visit/action labels to GoatCounter (see
below). This is a static app, not yet an offline-installable PWA: reloading the site
still needs its assets to be available.

Use a current browser with module workers, WebAssembly SIMD and exception handling, IndexedDB, and
Web Locks on HTTPS or localhost. Chrome on Apple Silicon has been exercised.
WebGPU is optional: the app checks availability and validates its integer
kernel against CPU results, then falls back to CPU if unavailable or lost.
Safari/Firefox behavior has not yet been validated end to end.

The browser alignment engine uses up to eight CPU workers when cross-origin
isolation and shared memory are available. Independent MUSCLE refinement windows,
genome-pair searches, breakpoint distances, seed occurrence lists, and backbone
pairs run concurrently. The static Pages build installs the isolation service
worker automatically; unsupported browsers use the serial engine. The compute
status and alignment log report the selected worker count.

### Publish

1. Commit and push the changes, including the WebAssembly assets and licenses.
2. In repository **Settings → Pages**, select **GitHub Actions** as the source.
3. Run **Deploy browser Mauve to Pages** from the Actions tab.

The manual workflow runs the JavaScript tests (including the real WebAssembly
engine), builds the static artifact, and deploys it. A separate **Browser and
reference tests** workflow runs the JavaScript, Python reference, and static
browser integration tests on pushes and pull requests that change `web/`.
No backend URL, API key,
or secret is required. Paths support both `/mauve/` project sites and custom
domains. Nothing has been published automatically.

To build a release yourself, choose a new output directory:

```sh
python3 web/build_pages.py --output /tmp/mauve-pages
python3 -m http.server 8766 --bind 127.0.0.1 --directory /tmp/mauve-pages
```

### Usage analytics

The Pages workflow uses the same [GoatCounter dashboard](https://jozhang97.goatcounter.com)
as Natural Preprint. It sets the public `MAUVE_GOATCOUNTER_CODE` to `jozhang97`;
no secret or API key is needed. Tracking starts after deploying this change.
Visits use a fixed `/mauve/` path and `Mauve Explorer` title so they remain separate
from `/natural-preprint/` and other sites in the shared dashboard.

Usage events are fixed labels prefixed with `mauve-`:

- `demo-opened`, `alignment-imported`, `annotations-imported`: successful operations.
- `alignment-submitted`: a local job was accepted, including reruns.
- `alignment-completed`: a running job finished and its imported result was saved.
  Polling, reopening a completed job, and manually retrying a saved-result import
  do not count another completion.
- `ncbi-search-completed`, `ncbi-genome-downloaded`: successful searches (including
  result pagination) and downloads.
- `block-fasta-downloaded`, `block-table-downloaded`, `job-artifact-downloaded`,
  `svg-downloaded`: a download was requested, not confirmation that it was saved.

Analytics payloads exclude sequences, filenames, genome/job/alignment IDs,
accessions, search queries, errors, URL queries/fragments, and referrers. The
provider still receives normal network connection information. No analytics
code runs in the compute workers; fixed completion messages reach the UI, which
counts them. The [GoatCounter JavaScript API](https://www.goatcounter.com/help/js)
handles counting, with bounded queuing and failures isolated from app operations.

Tracking requires an explicitly configured static build served over HTTPS and
is disabled on localhost and for Do Not Track visitors. Default local builds,
Python server mode, and browser tests send no analytics. Counts are approximate
because blocked scripts and opted-out visitors are excluded. Set
`MAUVE_GOATCOUNTER_CODE` to an empty string in `.github/workflows/pages.yml` and
redeploy to disable tracking. For another host, build with
`python3 web/build_pages.py --goatcounter-code YOUR_SITE_CODE`.

Tests stub the tracker without contacting GoatCounter:
`node --test web/browser-tests/analytics.test.mjs`. After deployment, open the
site, open the E. coli demo, export a view, and check the dashboard for `/mauve/`,
`mauve-demo-opened`, and `mauve-svg-downloaded`.

### Local storage and job lifetime

The browser has its own library, separate from `web/.data`. IndexedDB stores
validated alignment metadata, individual block members, annotations, normalized
job inputs, and artifacts. An alignment becomes visible only after every block
validates; a failed annotation replacement preserves the previous annotations.
Data belongs to this browser profile and origin. Clearing site data, private
browsing, or storage eviction can remove it; export important results.

Keep the tab open while a job runs. Closing it interrupts unfinished jobs;
returning marks them interrupted and allows a rerun using retained inputs.
Jobs are serialized across tabs with Web Locks, and cancellation terminates the
job's dedicated worker. Cancel a running job in the tab that started it. Job
outputs persist after completion. The current browser workflow retains normalized
input sequences and their original/normalized checksums, not the original upload
bytes. Completed logs and parameters are downloadable with the alignment.

### Acceleration and scaling

The architecture follows the useful pattern demonstrated by
[LocalFold](https://github.com/sokrypton/localfold): local computation in workers,
with WebGPU for suitable kernels. No LocalFold code or model weights are used.

- The real progressiveMauve C++ engine is compiled with `-O3 -msimd128` and runs
  in a separate worker. WebAssembly SIMD uses the browser's native CPU support,
  including Apple Silicon. A separate pthread build uses up to eight CPU threads
  for backbone pairs, recursive gap searches, breakpoint distances, and seed
  construction when shared memory is available, with a serial
  fallback. See [browser threading and deployment](wasm/README.md#browser-threads).
- Identity scans use a packed-byte WebGPU kernel with exact integer reductions.
  This uses Apple GPUs when exposed by the browser, and also supports other
  vendors. Small blocks use CPU to avoid GPU overhead. GPU buffers are bounded
  to 32 MiB per sequence; larger members currently use the CPU fallback.
- Imports stream text and commit one block at a time. Sequences use one byte per
  aligned base. Overview metadata is stored separately; opening an alignment
  does not read all DNA. Reads load members individually with a 64 MiB LRU cache.
  Page scans retain upcoming cached members when a block exceeds that limit,
  avoiding repeated eviction and reloading of the entire block. A separate
  4 MiB cache holds copied 8,192-column windows for oversized blocks, so nearby
  pages can avoid loading full members again.
  The API worker currently serializes operations. The standalone cache also
  shares pending member reads for overlapping callers, and page-window insertion
  rechecks cache state after storage reads to preserve byte accounting when
  another request fills or evicts the same window.
- Sparse ungapped-prefix indexes every 1,024 columns make coordinate jumps a
  binary search plus a short scan. Profiles are cached, and sequence rendering
  computes differences once per column instead of once per genome and column.
- XMFA span validation reuses the prefix index's base counts. Map rendering
  omits links wholly outside the viewport while preserving crossing links.
- XMFA and FASTA readers scan incoming chunks once and process at most 1,024
  lines per batch, reducing per-line asynchronous overhead and long-line rescans.
- The browser allows 2–64 inputs, with the existing 50 MiB/input, 100 million
  total input bases, and 256 MiB result/import limits. The WebAssembly heap has
  a 2 GiB ceiling and scratch files consume memory; these limits do not guarantee
  every workload fits. Genome-count capacity is experimental beyond the tested
  examples. Native progressive alignment still has expensive pairwise stages.

Measured on an Apple M4 Max with synthetic data (Chrome for the viewer, Node for the aligner):

| Operation | Result |
| --- | --- |
| Pairwise scan, 32 million columns | CPU 45 ms; WebGPU 13 ms, including transfer/readback |
| Import 32 genomes × 1 million aligned columns | 152 ms |
| First identity profile for that block | 58 ms |
| Cached profile / 100-column page | 1.1 ms / 0.6 ms |
| 10,000 indexed coordinate jumps | 5.9 ms |
| progressiveMauve, 12 genomes × 100,000 bases (first optimization pass) | 6.37 s, down from 12.08 s; 178 MiB peak Node process RSS |
| progressiveMauve, 128 genomes × 100,000 bases (first pass, single run) | 13:29, down from 34:00; 755 MiB peak Node process RSS |
| Zoomed SVG map, 32 genomes × 500 blocks | 3.0 ms, down from 26.2 ms |
| XMFA parsing only, 12 genomes × 1 million columns | 64.5 ms, down from 84.5 ms |
| Warm sequence page, 128 genomes × 750,000 columns | 10.3 ms, down from 32.8 ms; unchanged 64 MiB cache limit |

The map and parsing comparisons use five alternating measurements after warmup.
Full-view map rendering was essentially unchanged (286 ms); zooming reduced SVG
link paths from 15,500 to 62. Parsing produced identical sequences, indexes, and
metadata. These parser timings exclude IndexedDB storage. Raw measurements:
[map](benchmarks/results/map-2026-10-29.json),
[parser](benchmarks/results/import-2026-10-29.json), and
[128-genome engine](benchmarks/results/engine-128-2026-10-29.json).
The [paging comparison](benchmarks/results/paging-2026-10-29.json) uses three
fresh contexts per version, each measuring one cold and three warm pages. Cold
reads were unchanged; a smaller block fitting in cache remained at 0.4 ms per
warm page. Every returned base and genomic position was checked on both strands.

A subsequent [page-window comparison](benchmarks/results/page-windows-2026-10-29.json)
reduced warm pages for the same 128-genome workload from 14.9 to 1.0 ms.
Cold pages increased from 48.0 to 50.3 ms while populating windows; cached
sequence/index buffers are bounded to 68 MiB in total, excluding object overhead.
The [small-block comparison](benchmarks/results/page-windows-small-2026-10-29.json)
remained at 0.5 ms per warm page. These are paired measurements against the
preceding scan cache, not the original release. Unit checks additionally cover
gaps, reverse strands, window boundaries, eviction, failures, and early exits.

[CPU profile construction](benchmarks/results/profile-construction-2026-10-29.json)
reuses each bin's ending ungapped count as the next bin's starting count and
reads count fields directly. Complete one-million-column profiles improved
5–11% across identical, mixed, gapped, and ambiguous inputs in Chrome, with
identical output. These measurements exclude storage reads and GPU execution.

A subsequent [streaming-parser comparison](benchmarks/results/streaming-import-2026-10-29.json)
on two sequences of 25 million columns each reduced browser parsing from
244.7 to 188.0 ms for unwrapped lines (1.30×) and from 311.2 to 262.6 ms for
80-column wrapping (1.19×), with identical sequences, indexes, and metadata.
[FASTA normalization](benchmarks/results/normalize-2026-10-29.json) for two
one-million-base records improved from 13.3 to 10.4 ms in Node (1.28×), with
identical normalized bytes and record offsets. These are paired follow-up
comparisons against the preceding parser, not the original release.

GenBank parsing uses the batched reader without trimming fixed-column feature
lines. For five million bases and 10,000 features, [browser measurements](benchmarks/results/genbank-browser-2026-10-29.json)
improved wrapped input from 63.5 to 47.2 ms (1.35×); unwrapped input measured
38.9 to 37.7 ms. Sequence and annotation hashes match. [Node checks](benchmarks/results/genbank-2026-10-29.json)
also improved GenBank parsing, with XMFA and FASTA timings essentially unchanged.

Reverse-strand annotation verification uses a reusable 256-byte complement
table. For one million genomic bases, [Chrome measurements](benchmarks/results/verify-annotations-browser-2026-10-29.json)
improved canonical DNA from 20.5 to 5.6 ms and mixed ambiguity/gap data from
22.7 to 5.8 ms (3.65–3.93×), with identical verified-base counts. Forward checks
were essentially unchanged. [Node measurements](benchmarks/results/verify-annotations-2026-10-29.json)
show the same improvement; mismatch and coordinate-limit tests also pass.

A follow-up indexed verification loop resolves strand direction before scanning.
[Chrome measurements](benchmarks/results/verify-indexed-browser-2026-10-29.json)
show another 1.80–2.87× improvement over the table-only version: forward checks
10.2 → 3.56 ms, reverse checks 5.62 → 3.12 ms, and mixed reverse checks
5.80 → 2.68 ms. [Node measurements](benchmarks/results/verify-indexed-2026-10-29.json)
also improve, with the same counts and mismatch behavior.

Coordinate-prefix construction processes 1,024-column batches instead of
checking the index boundary for every base. [Node import measurements](benchmarks/results/rank-import-2026-10-29.json)
improved from 78.6 to 67.0 ms (1.17×). [Chrome measurements](benchmarks/results/rank-import-browser-2026-10-29.json)
improved unwrapped input from 39.7 to 31.9 ms and wrapped input from 47.6 to
41.9 ms, with identical sequence, prefix-index, and metadata hashes.

Viewer timings measure exploration of already aligned synthetic sequences. The
aligner measurement is a separate near-identical synthetic DNA workload in Node;
it does not predict performance on divergent full genomes. The first C++
optimization pass was 1.36–1.90× faster across five synthetic workloads. A direct
comparison after the scoring and seed changes measured
**1.48–2.12×** against the original release, with identical output artifacts and higher total Node process
memory. Subsequent traceback changes reduce memory and avoid clearing cells
before their first write. Loading row-constant gap penalties once adds a further
1.1–2.3% runtime improvement on four of five workloads, with the fifth flat.
A subsequent scalar deletion-score cache improved four workloads by another
roughly 1–4%, again leaving the ambiguous workload essentially unchanged.
See the [engine measurements and
profiling instructions](wasm/README.md#measurements-2026-10-29).
A fresh single-run [128-genome comparison](benchmarks/results/engine-128-current-2026-10-29.json)
measured the current engine at 17:42 versus 18:45 for the first optimization pass
(5.6% faster), with identical XMFA, tree, and backbone hashes. Peak Node RSS
was 754.9 versus 762.0 MiB; Wasm heap capacity was unchanged. Both fresh runs
used battery power. The earlier 13:29 result was measured hours earlier under
unrecorded power conditions and should not be used as a direct regression comparison.
The synthetic twelve-genome alignment test and an inversion/indel comparison
against the native executable pass. Larger, divergent biological datasets need
more validation. Current remaining scaling limits include the single-worker
aligner, in-memory scratch data, block-sized parsing, and SVG/DOM rendering.

SVG block rectangles share click, keyboard, and double-click handlers. A
[1,000-block map comparison](benchmarks/results/map-events-2026-10-29.json)
reduced retained JavaScript heap after garbage collection from 9.15 to 3.87 MB,
with byte-identical serialized SVG. Full-map rendering measured 764.5 → 778.5 ms
(about 2% slower); zoomed rendering was essentially unchanged. This is a memory
tradeoff, not an overall rendering-speed claim, and excludes native DOM memory.

Caching block coordinate bounds lets the map skip completely off-screen blocks
before sorting link endpoints or visiting each rectangle. A further
[1,000-block, 32-genome comparison](benchmarks/results/block-bounds-2026-10-29.json)
reduced zoomed rendering from 5.1 to 4.0 ms; full-map rendering was essentially
unchanged (767 to 772 ms). Rendered path/node counts match, with separate tests
for crossing links, viewport boundaries, panning, and metadata replacement.

Reading the three block-filter controls once per pass instead of once per block
reduced a zoomed [10,000-block, eight-genome map](benchmarks/results/map-filter-values-2026-10-29.json)
from 4.1 to 2.4 ms, with byte-identical SVG and essentially unchanged retained
JavaScript heap. [Search timings on 1,000 blocks](benchmarks/results/block-filter-values-2026-10-29.json)
were mostly unchanged; seven combinations of length, sharing, and isolation
filters were checked in every benchmark context. The map harness accepts
`--view zoomed` to focus measurements without rendering the entire map first.

Sharing one viewport-filtered block list between links and rectangles then
reduced the same zoomed map from [2.3 to 1.8 ms](benchmarks/results/map-shared-viewport-2026-10-29.json).
[Full-map rendering](benchmarks/results/map-shared-viewport-full-2026-10-29.json)
on 1,000 blocks and 32 genomes remained essentially unchanged (778.4 → 776.5 ms).
Both comparisons preserve exact SVG output and approximately the same retained
JavaScript heap.

Counting visible genomes once per track-control render avoids rebuilding the
visible-genome list for every checkbox. In the [track-control comparison](benchmarks/results/track-controls-2026-10-29.json),
64 visible genomes improved from 1.78 to 1.20 ms and 128 from 3.28 to 2.38 ms.
Small cases were essentially unchanged. Seven focused confirmation pairs with
only one visible genome were also flat, resolving an initial apparent slowdown.
Checkbox states, last-visible-track protection, ordering, and button labels
match across all measured cases.

Identity-window rectangles share one click callback per render. With 128 genomes
and 200 bins, the [identity-overlay comparison](benchmarks/results/identity-handlers-2026-10-29.json)
reduced retained JavaScript heap from 4.72 to 2.70 MB; rendering was essentially
flat (525.0 → 523.6 ms), and SVG bytes were identical. Clicks still use the current
selected block and offset after state changes. These heap figures exclude
native DOM memory. Use `map.py --identity-bins 200` to include this overlay.

Reusing the render pass's filtered blocks in the identity layer avoids another
filter scan. A [10,000-block, eight-genome comparison with 100 identity bins](benchmarks/results/identity-filter-reuse-2026-10-29.json)
measured 15.8 → 15.4 ms, with identical SVG and unchanged retained heap.

Block search matches genome names once per query, instead of repeatedly
searching and lowercasing them for each block member. With 64 genomes and 1,000
blocks, [browser measurements](benchmarks/results/block-search-2026-10-29.json)
show 2.9 → 0.6 ms for no-match queries and 3.1 → 0.8 ms for a block-name query.
Rendering all matching blocks was unchanged; result membership and order match.

Selecting a column in a 32-genome, 500-column sequence page updates only the
old and new selections. [Browser measurements](benchmarks/results/column-selection-2026-10-29.json)
improved from 7.78 to 2.03 ms per selection (3.84×), with keyboard focus and
accessibility states preserved. Sharing click/keyboard handlers per row then
reduced retained JavaScript heap after garbage collection from 3.29 to 1.69 MB
and handlers from 32,000 to 64; this is JS heap, not total browser memory.
[Row-handler measurements](benchmarks/results/row-events-2026-10-29.json) show
rendering at 254.5 → 249.0 ms and unchanged selection time. Reproduce using
`web/.venv/bin/python web/benchmarks/column-selection.py --url URL --baseline-app BASELINE_APP.js`.

CPU identity-profile counting uses a 256-byte nucleotide classification table.
[Browser measurements](benchmarks/results/profile-counts-2026-10-29.json) for one
million columns improved from 2.68 to 1.66 ms for identical DNA, 3.06 to 2.26 ms
for mixed DNA, and 1.96 to 1.74 ms with gaps. Ambiguity-heavy data was essentially
unchanged (4.84 to 4.86 ms). All counts matched, with exhaustive byte-pair tests
covering partial bins; the GPU path is unchanged.

Alignment logs retain chunks and a separate 32 KiB live tail, avoiding repeated
copies of the entire log. A [Node log-handling benchmark](benchmarks/results/logs-2026-10-29.json)
using real job handling, 4 KiB messages, and an in-memory store measured
20.2 → 6.4 ms for 1 MiB and 972.7 → 45.1 ms for 8 MiB. These timings exclude
IndexedDB latency and are not alignment speedups. Full log bytes and live tails
match; the existing log limit and failure handling are preserved. Reproduce with
`node --expose-gc web/benchmarks/logs.mjs BASELINE_JOBS.mjs web/mauve_web/static/browser/jobs.mjs OUTPUT.json`.

Reproduce the measurements against a running preview (a visible browser exposes
hardware WebGPU on macOS; headless Chrome may use the CPU fallback):

```sh
web/.venv/bin/python web/benchmarks/browser.py --url http://127.0.0.1:8766 --headful
node web/benchmarks/aligner.mjs 32 100000
```

For focused comparisons, save the earlier `static/app.js` and
`static/browser/core.mjs` from the revision being compared, then run:

```sh
web/.venv/bin/python web/benchmarks/map.py --url http://127.0.0.1:8766 --baseline-app /tmp/baseline-app.js
node --expose-gc web/benchmarks/import.mjs /tmp/baseline-core.mjs
web/.venv/bin/python web/benchmarks/paging.py --url http://127.0.0.1:8766 --baseline-store /tmp/baseline-store.mjs --baseline-worker /tmp/baseline-worker.mjs
web/.venv/bin/python web/benchmarks/import-browser.py --url http://127.0.0.1:8766 --baseline-core /tmp/baseline-core.mjs --columns 25000000
node --expose-gc web/benchmarks/normalize.mjs /tmp/baseline/genbank.mjs
```

For normalization comparisons, place the matching baseline `core.mjs` alongside
the baseline `genbank.mjs`.

### Browser tests and engine build

```sh
node --test web/browser-tests/*.test.mjs
web/.venv/bin/python -m pytest web/browser-tests -q
MAUVE_HEADFUL=1 web/.venv/bin/python -m pytest web/browser-tests/test_browser.py -k gpu -q
MAUVE_NATIVE_TESTS=1 web/.venv/bin/python -m pytest web/browser-tests/test_reference.py -q
```

Install `web/requirements-dev.txt` and `web/requirements-browser.txt` in the web
virtual environment for the Python/browser checks, plus Playwright Chromium or
set `MAUVE_CHROME_PATH`. Tests compare browser calculations against the Python
reference and exercise the real engine, local persistence, downloads, cancellation,
GPU/CPU parity, and `/mauve/` deployment paths. The native comparison defaults to
the bundled macOS executable; set `MAUVE_ALIGNER` for another platform.

See [wasm/README.md](wasm/README.md) for pinned upstream sources, licensing,
compatibility patches, build flags, and rebuild instructions.

## Python server mode

Apple Silicon Macs can use the [native multicore engine](native/README.md) in
local-server mode. Build it with `python3 web/native/build.py --work /tmp/mauve-native-build --output web/native/bin`,
then restart the server with `MAUVE_THREADS=8 ./web/run.sh`. This enables native
ARM64/NEON execution and bounded parallel genome-pair work. It does not enable
threading in the standalone website, which has its own pthread build. The generated
binary is local and is not included in Git.

The sections below describe the original Python/native server mode. Its data
location, eight-input limit, and background-job lifetime differ from the
standalone browser build described above.

### Run

Requires Python 3.11 or newer. From the repository root:

```sh
./web/run.sh
```

Open http://127.0.0.1:8765. The first launch creates `web/.venv` and installs dependencies (internet required). Subsequent launches work offline unless the dependency list has changed. Stop with Ctrl+C.

Use the header **Theme** selector to choose System, Light, or Dark. The preference is saved in your browser, follows operating-system changes in System mode, and applies to dialogs, tracks, and SVG exports.

Choose **Open E. coli demo** to load eight randomly sampled complete circular E. coli chromosomes with annotations for every strain, or **Import alignment** to select an `.xmfa` or Mauve `.alignment` file. Server imports persist in `web/.data/alignments.sqlite3`; the standalone app uses browser storage. The demo is prealigned, so no alignment job runs when it opens. The first load downloads compressed assets; subsequent opens reuse the saved alignment and annotations. Existing saved yeast alignments remain in your library.

The frozen sample contains MG-phbCAB-3-6, 104, E138, M-17, A16, MUD-KCA19, BH212, and A12. Sampling uses named strains with one complete annotated chromosome from current NCBI RefSeq E. coli assemblies; plasmids are excluded. One representative assembly per named strain enters the random pool. The [manifest](demo/ecoli/manifest.json) records the seed, pool size, accession versions, chromosomes, annotation dates, checksums, and alignment command. The compressed eligible pool is included for replay. This is a random sample of that eligible pool, not a phylogenetically balanced panel.

To reproduce the selected sample, run `web/.venv/bin/python web/demo/build_ecoli.py`, then `web/.venv/bin/python web/demo/build_ecoli.py --align`. Use `--sample` only to draw a new sample. The builder uses the native progressiveMauve executable and full default gapped alignment/refinement. Versioned sequence accessions and checksums identify the frozen data; NCBI annotation updates may change newly downloaded GenBank files. The original tiny yeast files remain regression-test fixtures, not the public demo.

- Click a block to inspect coordinates and aligned bases; double-click to focus its region.
- Highlighting a block shows its whole-block nucleotide identity beside each genome track, relative to **Compare with**, with the number of comparable base pairs. Block tooltips and SVG exports include the same identity. These percentages summarize the entire selected block regardless of zoom or sequence page; they are block identity, not a genome-wide ANI estimate. Gaps and ambiguous bases are excluded, and absent/no-comparable cases are labeled explicitly. **Selected block identity** toggles both track percentages and window profiles.
- Use the sticky Overview / Gene comparisons / Sequence / Genes & features navigation to move around the alignment. **Inspect sequence** jumps from the selected block to its bases.
- The block browser beneath the map shows block lengths and genome counts. Search by block ID or genome name; search filters the list without hiding map regions. Active map filters are indicated in the Display & filters heading.
- Use zoom, pan, Fit all, or a coordinate range such as `100-1000`.
- Track coordinates share an absolute scale. Blocks are not reference-normalized. Choose a **Comparison reference** for identity calculations; **Focus selected block in reference** navigates to that member’s native genomic range.
- Expand **Arrange tracks** to reorder or hide tracks. At least one stays visible. The map, sequence rows, column details, and comparison table share track order and visibility. The alignment and exported block data remain unchanged. Hiding the reference does not change which genome identity is calculated against.
- Open **Display & filters** to control connections, annotations, identity, minimum alignment-column length, or selected-block isolation. **Reset display** restores those options, clears block search/shared-only filtering, and restores all tracks in their original order. Length filtering is not Mauve’s LCB-weight algorithm.
- Selecting a block loads a windowed **identity plot** on its non-reference tracks. Bars span 0–100% identity; gray windows have no comparable bases. Up to 100 alignment-column windows are mapped to each member’s native coordinates, including reverse strands. Only pairs where both bases are A/C/G/T contribute; gaps and ambiguity are excluded. This is pairwise identity, not the original Mauve similarity statistic. Hiding another track does not change the reference or calculation.
- Viewer arrangement and filters reset when opening an alignment, and the page returns to the alignment title; these are not saved views.
- Matching colors connect block members. Colors repeat; use block IDs to distinguish them.
- Reverse-strand blocks have a hatch overlay. Their aligned bases are already reverse-complemented in XMFA; genomic positions decrease across the inspector.
- Coordinates are 1-based and inclusive. Track extent labels show the maximum coordinates found in the alignment. After annotation import, Fit all also includes the full GenBank sequence length.
- The inspector summarizes the whole selected block against the comparison reference: canonical-pair identity, canonical substitutions, columns containing a gap in either member, and remaining ambiguous columns. Counts are alignment columns, not variant calls or indel events. A reference absent from a block produces no comparison.
- **Sequence comparison**, directly below the overview, combines the sequence page (25, 50, or 100 columns) with per-genome coordinates and whole-block identity beside each row. Expand **Whole-block counts and comparison rules** for detailed counts. Matching and differing bases stay in context by default; **Isolate differences** filters the same page and retains original alignment-column numbers, so filtered spacing is not genomic distance. Differences compare all block members independently of reference and track visibility.
- Map zoom/pan/region changes navigate the selected block’s sequence to the first aligned base in the visible region (the high coordinate for a reverse member). The reference is preferred; if absent or hidden, a visible overlapping member is used. If none overlap, the previous sequence page is retained with an explanation. Purple marks below map tracks show the genomic spans of the current sequence page.
- Use **Jump to** for a 1-based alignment column or a genomic position in a chosen block member. Genomic mapping accounts for gaps and reverse strands; positions outside that member are rejected. Sequence paging and direct jumps focus the map on the resulting page. The map retains native coordinates, rather than normalizing all tracks to the reference.
- If filters hide the selected block, a message explains why the sequence remains open and offers **Reveal selected block**. An empty map offers **Clear filters**, **Show all genomes**, or **Fit all**, according to its cause. Fit all changes coordinates, not filters.
- Mobile defaults to 25 columns and compact genome-number labels, with full names, positions, and identity counts in the column details. Enable **Full genome labels on mobile** to expand the row labels. A visible scrolling hint appears when the sequence exceeds the available width.
- Click a base to select its column across genomes; left/right arrow keys move between displayed columns. The linked column detail shows each genome’s base, native coordinate and strand; **View locus** reveals that genome and focuses the overview around that position. Gaps have no genomic position or locus button. **Next page with differences** skips beyond the current page to the next unequal column. Reverse-strand genomic positions decrease across the sequence.

## Find genomes at NCBI

Click **Find NCBI genomes**, enter a numeric NCBI taxonomy ID (for example, `4932` for *Saccharomyces cerevisiae* or `2097` for *Mycoplasmoides genitalium*), and choose **Find genomes**.

The browser queries [NCBI Datasets](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/how-tos/genomes/get-genome-metadata/) for genome **assemblies**, including descendant taxa by default. Select **Exact taxon only** to exclude descendants. Results include accession/version, organism, strain, assembly level/status, release date, size, contig count, and paired accession. Current versions from both GenBank and RefSeq are shown by default; filters can restrict the source, include historical/suppressed versions, or search assembly names, strains, and submitters. Historical entries are not guaranteed to be downloadable. This is the genome assembly catalog, not every nucleotide record or the separate NCBI viral genome catalog.

Use Previous/Next to browse all matching pages, keeping selections across pages. A new search clears the selection. Paired GCA/GCF records are shown separately, not deduplicated; inspect their accessions to avoid unintentionally comparing paired versions of one assembly. Select up to the available 8 input slots, then **Download selected genomes**. Selected versioned genomic FASTAs are downloaded from NCBI and added to the alignment form. Review them and the alignment settings, explicitly enable record concatenation when needed, then start the alignment. They can be combined with uploaded local genomes.

Downloads run sequentially in the browser workflow. If one fails, earlier successful downloads remain staged, and retry downloads only the remaining selection. Keep the page open during download/review; staged selection is not restored automatically on reload. Once submitted, jobs persist independently of the browser. The backend retains source accession, metadata, retrieval timestamp, download URL, and sequence checksums in each input and its job manifest.

Assemblies above the current per-input limit are visible but cannot be selected. Metadata size estimates are checked before downloading; compressed packages and uncompressed FASTA content also have bounded sizes. This does not lift the 50 MiB/input, 100 million bases/job, or 256 MiB alignment-result limits. Multi-record genomes use the same explicit concatenation convention as local uploads.

Internet access is required on the server for search and downloads. Requests use the NCBI Datasets v2 API and are throttled locally. An optional `NCBI_API_KEY` environment variable is sent only in the upstream request header, never saved in provenance or returned to the browser. NCBI outages, throttling, and unavailable accessions appear as actionable errors; the app never silently substitutes another assembly version.

## Run an alignment

Click **Align sequences**, name the experiment, and choose **2–8 FASTA or GenBank files**, one genome per file. Uploads accept ungapped IUPAC DNA, at least 50 bases per genome, up to 50 MiB per file and 100 million bases across a job. For a file containing multiple records, explicitly enable concatenation in file order. Each file is normalized into a single FASTA record; offsets and original record names are retained in the job manifest. This can create artificial adjacency across contig boundaries, so interpret boundary-spanning alignments accordingly.

Optional settings expose collinearity (only when no rearrangements are expected), seed families, and a minimum pairwise LCB score. Other settings use the selected executable's defaults. The command is built from typed options, without a shell. See the [progressiveMauve parameter reference](https://darlinglab.org/mauve/user-guide/progressivemauve.html) for algorithm details.

Jobs run serially, with up to ten active/queued jobs. You can close the browser and return to the **Alignment jobs** list. Select a job to see its status and the last 32 KiB of its log, cancel a queued/running job, or open a successful result. Log output is buffered by the native program; a quiet log does not indicate a stalled job. Importing a completed result is atomic and cannot be cancelled. Successful results are automatically added to the alignment library; GenBank annotations can then be imported separately.

Download the XMFA, guide tree, backbone, full log, and provenance manifest from a successful job. The manifest records input filenames, record offsets, original and normalized SHA-256 checksums, executable version/checksum, options, exact argument list, and submission time. The command uses paths relative to that job's directory. **Rerun with same inputs** creates a new job using the retained inputs and options and the currently configured engine.

A failed job does not import an alignment. If a raw XMFA exists, it can be downloaded explicitly as unvalidated output. Completed alignment results up to 256 MiB can be imported. If an import fails after the native aligner finishes, **Import saved result** retries validation/import without rerunning the alignment. Existing jobs rejected by the old 50 MiB limit can also be recovered this way. Results above 256 MiB are retained for download. Logs above 25 MiB terminate the job. Uploaded originals, normalized inputs, intermediate files, and job outputs are retained under `web/.data/jobs/`; no automatic cleanup is performed. Jobs list the latest 100 submissions.

### Engine and worker setup

The runner supports macOS and Linux. It looks for `MAUVE_ALIGNER`, then `progressiveMauve` on PATH, then the repository's platform binary. The bundled macOS executable was successfully exercised on this machine; a `--version` probe determines availability on other machines. Override it when needed:

```sh
MAUVE_ALIGNER=/absolute/path/to/progressiveMauve ./web/run.sh
```

Restart after changing or installing an executable. A missing/incompatible engine disables job submission while leaving the viewer available. For hosting, install a compatible executable on the server; client-side installations are irrelevant.

Run **one server process/worker per data directory**. A process lock prevents competing workers. Graceful shutdown terminates the running process group and marks unfinished jobs interrupted. On restart, unfinished database entries are marked interrupted rather than silently rerun; choose Rerun to start a fresh job. An abrupt machine/process crash can leave native processes outside the server's control; this is not a distributed scheduler or a resumable alignment engine. Development reloads also interrupt jobs.

## Annotations and gene search

Select a genome in **Genome annotations**, then **Import GenBank**. The file must include its DNA sequence. The importer checks canonical A/C/G/T bases against every aligned region (reverse-complementing reverse-strand regions) and rejects mismatches or a source shorter than the alignment coordinates. Ambiguous bases are excluded from this check; the reported count is aligned base observations, not necessarily unique genomic positions. Matching aligned regions does not independently validate unaligned regions or annotation biology.

For a multi-record file, enable **Concatenate records in file order** only when that is the coordinate convention used to generate the alignment. Record lengths determine offsets; record boundaries appear as dashed lines. Single-record files need no option. Each E. coli demo strain has one complete circular chromosome; the legacy yeast test fixture exercises concatenated records.

Green arrows show annotation segments overlapping the selected alignment block, using each genome’s own block coordinates. No arrows are shown before selecting a block or for genomes absent from that block. Arrows are clipped to block boundaries; their direction reflects the native annotation strand. Click one for its gene name, locus tag, product, notes, and coordinates. Compound locations retain their separate segments; fuzzy boundaries are marked as approximate. Search gene names, locus tags, products, notes, types, or record names within the selected genome, then select a result to focus the viewer. Search results are paginated. The overview loads all matching annotation pages separately for each block member, so the first genome cannot consume a shared 500-feature allowance. Compound features must have an actual segment overlapping the block. Zooming changes visibility without changing the selected-block annotation set; dense overlaps share a display lane. Focusing a search result selects an overlapping block. These remain GenBank annotation features, including separate gene/CDS records.

Annotations persist and are replaced atomically per genome on a successful reimport. Invalid imports preserve existing annotations. Remote, unknown, and zero-length feature locations are rejected. This version supports GenBank, not GFF.

## All-pairs gene comparisons and core/pan genome

Open **Gene comparisons**, import GenBank annotations for every genome, and choose
**Compute all pairs**. This compares whole genomes, independent of zoom, reference,
and track visibility. Computation runs in a cancelable browser worker in both the
standalone app and Python-server viewer. Results are invalidated when annotations,
alignment, or matching settings change.

The gene universe includes non-pseudogene CDS loci, annotated rRNA/tRNA, and other
RNA types with an explicit `/experiment` qualifier. A stricter experimental-only
RNA option is available. Gene/CDS records are not double-counted; fuzzy locations,
unknown strands, and repeated annotations of the same locus are excluded.
Older saved annotations must be reimported to retain evidence and topology.

Gene families are inferred from Mauve XMFA alignment columns, using default
70% reciprocal gene coverage and 60% nucleotide identity. These thresholds follow
the original Java ortholog exporter's defaults, but this implementation does not
use its backbone filtering and is not an exact port of that exporter. Coverage
counts aligned non-gap base pairs over each gene's full annotated parts; identity
uses canonical A/C/G/T pairs only. Matches require the same feature type and
compatible alignment orientation. Connected components of qualifying matches form
families; unmatched loci form their own families. Consequently, missing annotations,
unaligned homologs, and transitive matches affect the inferred core/pan genome.
This is not a separate protein-based orthology or paralogy search.

The metric selector displays an all-pairs heatmap; the expandable pair table shows
numerators, denominators, gene/family totals, and duplicate exclusions:

- **Content Jaccard:** shared families / union of distinct families within the pair.
- **Actual adjacency Jaccard:** intersection / union of strand-aware family-end
  neighbor pairs, without removing unshared genes. Repeated pair types count once.
- **Shared-gene adjacency conservation:** `2 × preserved / (pairs A + pairs B)`
  after removing unshared families and any family with multiple copies in either
  genome. The denominator is symmetric.
- **Shared-gene DCJ:** `n − cycles` for the same unique shared markers on circular
  chromosomes. Each chromosome wraps independently; there are no artificial links
  between records. Rotation and whole-chromosome reverse complementation preserve
  these metrics. Empty denominators report N/A.

Known linear records and overlapping alignment blocks are rejected for this
analysis. Missing topology is assumed circular and reported. Origin-spanning genes
are ordered across the origin; overlapping genes use forward start-coordinate
order. Duplicate families remain in content/core/pan counts, with their copy counts
visible, but ambiguous shared copies are excluded from order/DCJ.

The core/pan section shows pan, strict core, single-copy core, accessory, and
genome-specific families, plus occupancy across genomes and a searchable, paged
family presence/copy matrix. Export the pair table and family membership as TSV,
or the complete results and settings as JSON. Results are recomputed on demand;
export them for a durable analysis record.

Checks: `node --test web/browser-tests/gene-analysis.test.mjs` verifies metrics,
matching, circular-origin handling, and DCJ against all 105 four-gene adjacency
matchings using exhaustive shortest paths. From `web/`, run
`.venv/bin/python -m pytest browser-tests/test_gene_analysis.py -q` for static and
server browser workflows, exports, and mobile layout. Real biological orthology
validation remains necessary before interpreting inferred families as curated truth.

## Exports

- Open **Export** in the overview heading. **Export view as SVG** saves the current genome overview with its styles, selected region, visible annotations, and block connections. It does not include the sequence inspector or offscreen features.
- **Download block table** exports all block members as TSV, with block ID, alignment column count, genome ID, 1-based start, inclusive end, and strand.
- **Download block as aligned FASTA** saves all columns of the selected block, preserving gaps and XMFA alignment orientation (including reverse-complemented reverse-strand records). FASTA identifiers use sequence IDs; coordinate and strand metadata follow the identifier.

## Development

```sh
cd web
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m uvicorn mauve_web.app:create_app --factory --reload --port 8765
```

The backend is FastAPI, with a SQLite store and Biopython for GenBank parsing. The frontend is plain JavaScript, SVG, and CSS, with no build step, CDN, or external asset requests. The same process serves the UI and `/api` routes. Interactive API documentation is at `/docs`.

- `mauve_web/xmfa.py`: parsing, validation, strand-aware coordinate mapping.
- `mauve_web/app.py`: import, persistence, feature search, downloads, and paged sequence API.
- `mauve_web/ncbi.py`: taxon/assembly search, bounded downloads, and source provenance.
- `mauve_web/jobs.py`: sequence staging, executable discovery, persistent queue, cancellation, and provenance.
- `mauve_web/annotations.py`: GenBank locations, record offsets, and sequence verification.
- `mauve_web/static/`: viewer and styles.
- `tests/`: real fixture, reverse strands, gaps, malformed files, API persistence and limits.

Optional browser integration tests run against an isolated temporary database and server:

```sh
cd web
.venv/bin/python -m pip install -r requirements-browser.txt
.venv/bin/python -m playwright install chromium
MAUVE_BROWSER_TESTS=1 .venv/bin/python -m pytest -q
```

Alternatively set `MAUVE_CHROME_PATH` to an installed Chrome executable. Browser tests cover annotation search/import, source mismatch errors, persistence, downloads, navigation, and mobile layout. They save screenshots in pytest's temporary test directory. Add `MAUVE_NATIVE_TESTS=1` to exercise the real executable with two synthetic 5,000-base genomes; with browser tests enabled this also checks job submission, downloads, and opening results. Set `MAUVE_NCBI_TESTS=1` to enable live NCBI search/download tests; combining it with `MAUVE_NATIVE_TESTS=1` also downloads and aligns two small bacterial genomes end to end. NCBI unit/browser tests otherwise use controlled responses to test pagination, errors, source validation, and retry after a partial download. Theme tests cover system preference, persistence, dialogs, and SVG export.

Other runner tests use controlled subprocesses to cover failures, cancellation, restart recovery, and worker exclusivity.

### Backend performance

Identity profiles and next-difference searches use NumPy scans in chunks of at most
65,536 columns, preserving the canonical-base, gap, and ambiguity rules above.
Genomic jumps use a binary search over ungapped prefix lengths instead of a Python
loop over preceding columns. A process-local LRU cache retains up to 32 decoded
blocks within a 64 MiB estimated object-size budget. Oversized blocks are served
without caching; concurrent requests for a cacheable block share its initial load.
Imported blocks are immutable, and restarting the server clears the cache. This
budget covers retained decoded objects, not total process memory or active requests.

Run the synthetic benchmark without touching your alignment library:

```sh
cd web
.venv/bin/python benchmarks/backend.py --genomes 8 --columns 1000000
```

An optional `--baseline /path/to/previous/xmfa.py` compares profile and coordinate
implementations and verifies identical profile output. On the development machine,
eight genomes with one million alignment columns took approximately 581 ms before
and 19 ms after for an identity profile (median of three runs). These improvements
speed up exploration of completed alignments, not the native progressiveMauve
calculation. The eight-input job cap remains a website policy, not a demonstrated
engine limit; viewer benchmarks with more genomes do not validate native job capacity.

## Hosting later

The browser uses relative API URLs and sends file contents, never local filesystem paths. The backend can therefore run on another machine without redesigning the UI. On a hosted instance, imported files are transferred to that server.

Set `MAUVE_DATA_DIR` to a persistent directory, `PORT` to the desired port, and `MAUVE_HOST` to the bind address (default `127.0.0.1`). For example, on a private server:

```sh
MAUVE_DATA_DIR=/srv/mauve-data MAUVE_HOST=0.0.0.0 PORT=8765 ./web/run.sh
```

There is currently one shared workspace and no authentication. Put it behind authenticated HTTPS access before exposing it publicly. SQLite and the serial job worker fit a single server with a persistent disk; multi-user permissions and distributed storage are future work.

## Current scope

This is an initial alignment viewer, not a replacement for every Mauve feature. It runs progressiveMauve jobs and provides selected-block pairwise identity plots but does not yet reproduce Mauve similarity profiles, call SNPs, reorder contigs, score assemblies, or export gene-level ortholog alignments. All-pairs alignment-derived gene-family comparisons, circular shared-gene DCJ, core/pan summaries, GenBank features, and overview SVG/FASTA/TSV exports are supported; these are not a claim of complete parity with the Java application. Alignment imports are limited to 256 MiB; individual sequence/GenBank uploads remain limited to 50 MiB. Alignment uploads are spooled to disk and parsed block by block into an atomic SQLite transaction. Overview metadata lives in a separate table, so loading a map or exporting coordinates does not read the aligned DNA. Sequence inspection still loads the selected block into memory, and the browser still renders all overview blocks with SVG. A five-genome yeast result (68.4 MiB, 46 blocks) was recovered and checked through the browser, including its largest 4.5-million-column block; this is not a general benchmark of all files up to the limit. Indexed viewport queries, background uploads, and canvas rendering remain scaling work.

The XMFA parser accepts aligned DNA (including IUPAC ambiguity codes), validates coordinate spans and equal column counts, and handles absent `0-0` records. It does not verify source sequence identity, detect overlapping blocks, or interpret sequence IDs as contig boundaries. GenBank annotation import adds explicit record boundaries and verifies canonical bases against those source sequences.

## Fresh original-versus-current engine benchmark

A fresh comparison of the original release against the current V7 engine used
three alternating runs per engine per workload, each in a new Node process on
an Apple M4 Max running on battery power. Times below are median alignment
runtime, excluding module loading, input staging, and output validation.
All 30 runs passed exact XMFA, guide-tree, and backbone hash comparisons and
parsed genome-extent checks. These inputs are synthetic, not full biological
genomes. [Raw timings and memory measurements](benchmarks/results/engine-final-before-after-2026-10-29.json).

| Workload | Genomes × bases | Original | Current | Speedup |
| --- | --- | --- | --- | --- |
| Similar | 12 × 100,000 | 12.041 s | 5.416 s | 2.22× |
| Divergent | 4 × 20,000 | 2.004 s | 1.271 s | 1.58× |
| Rearranged | 4 × 50,000 | 1.177 s | 0.713 s | 1.65× |
| Repeats | 4 × 50,000 | 1.087 s | 0.647 s | 1.68× |
| Ambiguous | 4 × 20,000 | 0.505 s | 0.327 s | 1.55× |

## Optimization research checkpoint

The autonomous research loop was stopped at the user’s request after completing
both fresh 128-genome runs. Final checks: 40 Node tests passed; 11 browser/build
tests passed and one optional reference check was skipped. The retained C++
engine also passed differential profile-score, seed, traceback, coordinate,
and homology-state checks.

Unpromoted experiments for a future session:

- [Retaining cached members during profile scans](benchmarks/results/member-scan-profile-experiment-2026-10-29.json)
  reduced warm profile time from 233.1 to 201.3 ms for 128 × 750,000 columns,
  with matching output hashes. The prototype also changes difference and FASTA
  scans; those branches still need validation before promotion. Sources and
  harness are in `/tmp/mauve-cache-concurrency/` and may be temporary.
- Reusing one GPU reference buffer per profile passed four mock-device ownership,
  overlap, failure-cleanup, and fallback tests. Real-device performance is
  unmeasured; the prototype remains in `/tmp/mauve-gpu-reference/`.
- MUSCLE alignment construction starts with 500 columns and can repeatedly grow
  and copy its buffers. Reserving space from the known alignment path is a
  candidate for investigation; no implementation or timing claim yet.

The [cache concurrency comparison](benchmarks/results/cache-concurrency-2026-10-29.json)
showed no viewer speedup: API operations are serialized. Its retained changes
are defensive cache correctness fixes, covered by direct overlapping-call tests.

## Remaining work, in priority order

1. **Scientific validation:** compare coordinates, inversions, indels, and repeat-rich examples against the original viewer and real research datasets. Current tests establish specific behaviors, not complete scientific parity.
2. **Similarity and navigation:** extend selected-block pairwise identity to scalable whole-alignment profiles, add reference-normalized navigation and track flipping, and validate against original Mauve statistics. Track reordering/visibility and column-length filtering are implemented.
3. **Analysis exports:** SNP/indel tables, pairwise identity/coverage summaries, then gene-level ortholog alignments and validation of inferred family assignments against curated orthology.
4. **Scale:** add sequence-coordinate indexes and viewport queries, render dense data with canvas, and benchmark more large comparisons. Block-by-block imports and separate overview metadata are implemented.
5. **Workspace management:** saved views, annotation auto-attachment/GFF support, rename/delete controls, input cleanup, and clearer storage/job resource reporting.
6. **Specialized Mauve tools:** contig ordering, assembly scoring, and extensions beyond unique-marker circular DCJ (linear chromosomes and duplicate-copy resolution). Multi-user hosting requires authentication/authorization and a separate durable worker design.

The overview’s **Display & filters → Align tracks on block click** option shifts each chromosome horizontally so the clicked base and its corresponding alignment-column bases line up, following Mauve’s align-view behavior. Zoom and chromosome orientation stay unchanged; tick labels remain native genome coordinates. Genes, identity windows, links, and sequence-page markers use the same shifts. Clicks in gaps use a nearby column shared with the anchor, searching neighboring sequence pages when necessary. Members absent from the block, or with no comparable column anywhere in that block, retain their previous position. Turn the option off to restore the common coordinate origin.

In this mode, single chromosomes annotated as circular wrap in both directions at their full GenBank record length. Dashed origin marks indicate the last-base-to-base-1 boundary, and per-track ticks retain native coordinates. Panning can cross that boundary; wrapped blocks remain clickable and retain native sequence/annotation coordinates. Linear, unknown-topology, and concatenated multi-record inputs do not wrap.

In aligned mode, the Region control uses the reference genome’s native coordinates. A circular range such as `1950-250` crosses the origin; the range summary names the reference and marks origin crossings. Zoom to selected block fits its members in aligned mode, or its reference member otherwise, with a small margin. Fit all clears rotations while retaining the alignment toggle.

Circular tracks display at most one chromosome turn at a shared base-pair scale. Shorter chromosomes leave blank space rather than repeating to fill the longest track. If the viewing cut falls inside a gene, its two edge fragments cover disjoint native base ranges; tooltips identify the visible bases and continuation. Block, annotation, identity, and sequence-page layers share each genome’s clipping boundary.
