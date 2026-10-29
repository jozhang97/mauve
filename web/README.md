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

Use a current browser with module workers, WebAssembly SIMD, IndexedDB, and
Web Locks on HTTPS or localhost. Chrome on Apple Silicon has been exercised.
WebGPU is optional: the app checks availability and validates its integer
kernel against CPU results, then falls back to CPU if unavailable or lost.
Safari/Firefox behavior has not yet been validated end to end.

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
site, open the yeast demo, export a view, and check the dashboard for `/mauve/`,
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
  including Apple Silicon. Alignment currently uses one CPU worker, not the GPU.
- Identity scans use a packed-byte WebGPU kernel with exact integer reductions.
  This uses Apple GPUs when exposed by the browser, and also supports other
  vendors. Small blocks use CPU to avoid GPU overhead. GPU buffers are bounded
  to 32 MiB per sequence; larger members currently use the CPU fallback.
- Imports stream text and commit one block at a time. Sequences use one byte per
  aligned base. Overview metadata is stored separately; opening an alignment
  does not read all DNA. Reads load members individually with a 64 MiB LRU cache.
- Sparse ungapped-prefix indexes every 1,024 columns make coordinate jumps a
  binary search plus a short scan. Profiles are cached, and sequence rendering
  computes differences once per column instead of once per genome and column.
- The browser allows 2–64 inputs, with the existing 50 MiB/input, 100 million
  total input bases, and 256 MiB result/import limits. The WebAssembly heap has
  a 2 GiB ceiling and scratch files consume memory; these limits do not guarantee
  every workload fits. Genome-count capacity is experimental beyond the tested
  examples. Native progressive alignment still has expensive pairwise stages.

Measured on an Apple M4 Max in Chrome, synthetic data:

| Operation | Result |
| --- | --- |
| Pairwise scan, 32 million columns | CPU 45 ms; WebGPU 13 ms, including transfer/readback |
| Import 32 genomes × 1 million aligned columns | 152 ms |
| First identity profile for that block | 58 ms |
| Cached profile / 100-column page | 1.1 ms / 0.6 ms |
| 10,000 indexed coordinate jumps | 5.9 ms |
| progressiveMauve, 32 genomes × 100,000 bases | 56.4 s; 222 MiB peak Node process RSS |

Viewer timings measure exploration of already aligned synthetic sequences. The
aligner measurement is a separate near-identical synthetic DNA workload in Node;
it does not predict performance on divergent full genomes.
The synthetic twelve-genome alignment test and an inversion/indel comparison
against the native executable pass. Larger, divergent biological datasets need
more validation. Current remaining scaling limits include the single-worker
aligner, in-memory scratch data, block-sized parsing, and SVG/DOM rendering.

Reproduce the measurements against a running preview (a visible browser exposes
hardware WebGPU on macOS; headless Chrome may use the CPU fallback):

```sh
web/.venv/bin/python web/benchmarks/browser.py --url http://127.0.0.1:8766 --headful
node web/benchmarks/aligner.mjs 32 100000
```

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

Choose **Open yeast demo**, or **Import alignment** to select an `.xmfa` or Mauve `.alignment` file. Imports persist in `web/.data/alignments.sqlite3`. The demo alignment and GenBank annotations are copied from `testdata/small.alignment` and `testdata/S_cerevisiae_small.gbk`.

- Click a block to inspect coordinates and aligned bases; double-click to focus its region.
- Use the sticky Overview / Sequence / Genes & features navigation to move around the alignment. **Inspect sequence** jumps from the selected block to its bases.
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

For a multi-record file, enable **Concatenate records in file order** only when that is the coordinate convention used to generate the alignment. Record lengths determine offsets; record boundaries appear as dashed lines. Single-record files need no option. The yeast demo demonstrates two concatenated chromosomes.

Green arrows show feature segments and strand. Click one for its gene name, locus tag, product, notes, and coordinates. Compound locations retain their separate segments; fuzzy boundaries are marked as approximate. Search gene names, locus tags, products, notes, types, or record names within the selected genome, then select a result to focus the viewer. Search results are paginated. The overview shows up to 500 features per region and warns when truncated; dense overlaps share a display lane.

Annotations persist and are replaced atomically per genome on a successful reimport. Invalid imports preserve existing annotations. Remote, unknown, and zero-length feature locations are rejected. This version supports GenBank, not GFF.

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

This is an initial alignment viewer, not a replacement for every Mauve feature. It runs progressiveMauve jobs and provides selected-block pairwise identity plots but does not yet reproduce Mauve similarity profiles, call SNPs, reorder contigs, score assemblies, or export orthologs. GenBank features and overview SVG/FASTA/TSV exports are supported; these are not a claim of complete parity with the Java application. Alignment imports are limited to 256 MiB; individual sequence/GenBank uploads remain limited to 50 MiB. Alignment uploads are spooled to disk and parsed block by block into an atomic SQLite transaction. Overview metadata lives in a separate table, so loading a map or exporting coordinates does not read the aligned DNA. Sequence inspection still loads the selected block into memory, and the browser still renders all overview blocks with SVG. A five-genome yeast result (68.4 MiB, 46 blocks) was recovered and checked through the browser, including its largest 4.5-million-column block; this is not a general benchmark of all files up to the limit. Indexed viewport queries, background uploads, and canvas rendering remain scaling work.

The XMFA parser accepts aligned DNA (including IUPAC ambiguity codes), validates coordinate spans and equal column counts, and handles absent `0-0` records. It does not verify source sequence identity, detect overlapping blocks, or interpret sequence IDs as contig boundaries. GenBank annotation import adds explicit record boundaries and verifies canonical bases against those source sequences.

## Remaining work, in priority order

1. **Scientific validation:** compare coordinates, inversions, indels, and repeat-rich examples against the original viewer and real research datasets. Current tests establish specific behaviors, not complete scientific parity.
2. **Similarity and navigation:** extend selected-block pairwise identity to scalable whole-alignment profiles, add reference-normalized navigation and track flipping, and validate against original Mauve statistics. Track reordering/visibility and column-length filtering are implemented.
3. **Analysis exports:** SNP/indel tables, pairwise identity/coverage summaries, then ortholog exports with explicit gap, ambiguity, and missing-data rules.
4. **Scale:** add sequence-coordinate indexes and viewport queries, render dense data with canvas, and benchmark more large comparisons. Block-by-block imports and separate overview metadata are implemented.
5. **Workspace management:** saved views, annotation auto-attachment/GFF support, rename/delete controls, input cleanup, and clearer storage/job resource reporting.
6. **Specialized Mauve tools:** contig ordering, assembly scoring, and DCJ rearrangement distances as the research workflow needs them. Multi-user hosting requires authentication/authorization and a separate durable worker design.
