# progressiveMauve in WebAssembly

The checked-in `mauve_web/static/wasm/progressiveMauve.{mjs,wasm}` runs the actual
progressiveMauve algorithm, including libMems, libGenome and MUSCLE. It is not a
pairwise alignment substitute. Each job gets a new worker and Emscripten instance;
terminating that worker cancels computation and its descendant pthread workers.

## Rebuild

Install/activate [Emscripten 4.0.15](https://emscripten.org/docs/getting_started/downloads.html)
in a separate directory, then run:

```sh
source /path/to/emsdk/emsdk_env.sh
python3 web/wasm/build.py --work /tmp/mauve-wasm-build --jobs 4
python3 web/wasm/build.py --work /tmp/mauve-wasm-threaded-build --jobs 4 --threaded
python3 web/wasm/test_kernels.py --work /tmp/mauve-wasm-build
node --test web/browser-tests/wasm.test.mjs
```

For a focused experiment, append `--case traceback` to the kernel command
(or `profile_scores`, `seed_lookup`, `coordinates`, `homology_states`, `thread_pool`). Repeat
`--case` to select several kernels. Omitting it runs the complete suite.

Python 3.11.8+ (tar extraction filters), Git, and the Emscripten SDK are build
requirements. A static release needs none of them on the visitor's machine.
`build.py` pins all four upstream Git revisions and verifies the Boost 1.65.1
archive SHA-256. It compiles all sources, including dependencies, on each run.
The script and `optimizations/` sources are also included in the Pages artifact
beside the binaries and licenses. `SOURCES.json` records upstream revisions,
build configuration, local source hashes, and the resulting binary hash.

The compatibility changes are intentionally small and applied by the script:

- Include Boost's workaround macro header explicitly.
- Match libc++'s `std::swap` exception specification.
- Implement the upstream libc file-size branches using `stat`.

No alignment/scoring heuristic was changed. The build uses `-O3 -msimd128 -flto`,
native WebAssembly C++ exception support, an 8 MiB stack, and growable wasm32 memory capped at 2 GiB.
It does not use fast-math or OpenMP. SIMD lets the browser use its native vector
instructions, including on Apple Silicon. The serial engine remains available as a fallback. A separate pthread build
parallelizes backbone HMM pairs, recursive gap searches, pairwise breakpoint
distances, and seed-occurrence construction; other alignment stages remain serial. WebGPU accelerates viewer identity scans, not progressiveMauve itself.
The runtime must support WebAssembly exception handling as well as SIMD. The
job form reports an unsupported exception runtime before starting a worker.

## C++ optimizations and profiling

The changes target hotspots observed in an optimized C++/Wasm CPU profile:

- MUSCLE's nucleotide profile scores are computed one row at a time, hoisting
  scoring-mode selection and sparse weights out of the cell loop. The order of
  floating-point operations and dynamic-programming tie-breaking are preserved.
  Other scoring modes retain the scalar scorer.
- Nucleotide score columns are packed once per alignment and evaluated four
  columns at a time with Wasm SIMD. Small alignments and non-nucleotide profiles
  retain scalar row scoring. The extra buffer uses 16 bytes per column.
- Seed extraction packs four selected DNA symbols per lookup using an 8 KiB
  constant table, retaining the original path for unsupported seed dimensions.
- Homology posterior decoding resolves its state identifier once per run,
  avoiding two string/map lookups for every sequence position.
- A gapless coordinate translation updates the origin without allocating and
  copying identical alignment bitmaps or rebuilding their rank indexes.
- Rank indexes use population counts over bitset blocks rather than testing
  each bit. Partial final index intervals retain the original behavior.
- Single-child intervals reuse the child's bitmap after checking its dimensions
  and residue counts. Missing rows remain zero; surplus bits take the original
  truncation path.
- Traceback cache rows share one contiguous allocation and use a 64-cell growth
  margin instead of 1,024 extra cells in both dimensions. Cell initialization,
  recurrence order, and traceback choices are unchanged.
- Traceback initialization clears only boundary rows/columns. The recurrence
  initializes each interior cell before use, avoiding a full-grid clear.
- Gap-open and gap-close penalties that are constant across a DP row are loaded
  once, preserving the recurrence and avoiding repeated alias-sensitive loads.
- The current deletion score remains in a scalar across traceback-byte writes,
  avoiding an alias-sensitive reload before the match recurrence.
- Link-time optimization lets the compiler optimize across library boundaries.
  [Native Wasm exceptions](https://emscripten.org/docs/porting/exceptions.html)
  replace the JavaScript exception wrappers; exception handling remains enabled.

Build a baseline with the original implementation paths and compiler settings:

```sh
python3 web/wasm/build.py --work /tmp/mauve-wasm-build --baseline --output /tmp/mauve-baseline
python3 web/wasm/build.py --work /tmp/mauve-wasm-build --output /tmp/mauve-optimized
python3 web/benchmarks/compare-engines.py \
  --baseline /tmp/mauve-baseline/progressiveMauve.mjs \
  --candidate /tmp/mauve-optimized/progressiveMauve.mjs \
  --repeats 3 --output /tmp/mauve-comparison.json
```

The comparison runs each alignment in a fresh Node process, alternates engine
order, and rejects any difference in XMFA, guide-tree, or backbone artifact
hashes. Its five deterministic workloads cover nearly identical genomes,
substitutions, inversions/indels, repeats, and ambiguous bases. These are
synthetic regression cases, not a biological performance benchmark.

For an experimental 128-genome scaling check, the benchmark harness accepts a
higher genome count than the website's 64-input limit:

```sh
MAUVE_BENCHMARK_PROGRESS=1 python3 web/benchmarks/compare-engines.py \
  --baseline /tmp/mauve-baseline/progressiveMauve.mjs \
  --candidate web/mauve_web/static/wasm/progressiveMauve.mjs \
  --genomes 128 --bases 100000 --repeats 1 --timeout 7200 \
  --output /tmp/mauve-128-comparison.json
```

Progress messages go to stderr at most once every 30 seconds when the engine
emits output. Their percentages describe individual engine phases, not total
job completion. Completed runs are saved even while the next engine is running.

For function names in CPU profiles, add `--profiling` to either build (this
preserves names without disabling optimization), then run:

```sh
node --cpu-prof --cpu-prof-name=mauve.cpuprofile web/benchmarks/engine.mjs \
  /tmp/mauve-optimized/progressiveMauve.mjs similar 12 100000
```

Open the `.cpuprofile` in Chrome DevTools. Profiling is for identifying hotspots;
use runs without the profiler for reported timings.

A [refreshed V5 profile](../benchmarks/results/engine-current-profile-2026-10-29.json)
on 12 similar genomes of 100,000 bases attributes about 36% of samples to
MUSCLE global alignment and 6.5% to profile construction. The report identifies
both the production binary and its relinked profiling build; these proportions
describe this workload and are not speedup measurements.

### Measurements, 2026-10-29

Keeping the current deletion score in a scalar improved final-binary medians
by about 1–3.7% on four workloads; the ambiguous case was effectively flat (0.3%).
[Deletion-score measurements](../benchmarks/results/engine-local-deletion-score-2026-10-29.json)
use three alternating pairs per workload, identical artifacts, and 729 exact
traceback-cell cases. Seven prototype confirmation pairs on the divergent
case improved by 3.2%. This adds no heap buffers.

Loading row-constant gap penalties once improved final-binary medians by
1.1–2.3% on four workloads; the ambiguous case was essentially unchanged (0.2%).
[Row-gap measurements](../benchmarks/results/engine-row-gaps-2026-10-29.json)
compare three alternating pairs per workload, with identical artifacts and no
additional heap buffers. All 729 traceback-cell cases pass. Seven prototype
confirmation pairs on the divergent case also improved by 2.3%.

Deferred traceback initialization improved measured runtime by
1.1–2.2% across all five workloads, with identical artifacts.
[Final-binary measurements](../benchmarks/results/engine-lazy-traceback-2026-10-29.json)
identify both binaries. Differential tests compare every traceback byte, exact
scores, and final paths over 729 cases, including buffer reuse and tied scores.

The traceback-cache allocation change reduced Wasm heap capacity on the divergent
case from 48.0 to 43.4 MiB with unchanged runtime. Other cases retained the same
heap capacity; median process RSS generally decreased. A seven-pair follow-up
on repeats measured 672.2 → 671.6 ms, resolving an initial 1% timing regression.
[Traceback-cache measurements](../benchmarks/results/engine-traceback-2026-10-29.json)
include both reproducible binary hashes and all output hashes. The cache is
also checked against the original allocation path in 729 score/path cases.

The scoring/seed-lookup build (before the traceback-cache change) was also
compared directly against the original release,
with three alternating fresh-process runs per case. All XMFA, guide-tree, and
backbone artifacts matched byte for byte.

| Workload | Original release | Scoring/seed build | Speedup |
| --- | ---: | ---: | ---: |
| similar, 12 × 100,000 bases | 12.038 s | 5.682 s | 2.12× |
| divergent, 4 × 20,000 bases | 1.998 s | 1.349 s | 1.48× |
| rearranged, 4 × 50,000 bases | 1.176 s | 0.745 s | 1.58× |
| repeats, 4 × 50,000 bases | 1.084 s | 0.673 s | 1.61× |
| ambiguous, 4 × 20,000 bases | 0.504 s | 0.333 s | 1.51× |

[Direct original-release comparison](../benchmarks/results/engine-current-2026-10-29.json)
includes peak process RSS and Wasm heap capacity. The larger 32/128-genome
measurements below apply to the first optimization pass only.

Apple M4 Max, Node 22.23.3, three fresh-process runs per engine and case.
The following table and the 32/128-genome checks describe the first optimization
pass. Later passes add packed scoring and seed lookup.
Times are medians for `callMain`, excluding module startup, input staging, and
result parsing. [Raw timings, output hashes, and peak RSS](../benchmarks/results/engine-2026-10-29.json)
identify both binaries by SHA-256.

| Synthetic workload | Previous engine | Optimized engine | Speedup |
| --- | ---: | ---: | ---: |
| Similar, 12 × 100,000 bases | 12.079 s | 6.367 s | 1.90× |
| Divergent, 4 × 20,000 bases | 2.005 s | 1.470 s | 1.36× |
| Inversions/indels, 4 × 50,000 bases | 1.178 s | 0.785 s | 1.50× |
| Repeats, 4 × 50,000 bases | 1.089 s | 0.722 s | 1.51× |
| Ambiguous bases, 4 × 20,000 bases | 0.506 s | 0.352 s | 1.44× |

All three output artifacts match byte for byte on every run. The faster build
has a memory tradeoff: median peak Node process RSS on the 12-genome workload
increased from 133 to 178 MiB. Smaller cases increased from 69–120 to 147–179 MiB.
This is whole-process memory, not just the Wasm heap; in a separately inspected
four-genome rearrangement run both versions used a 16 MiB Wasm heap. The release
worker is terminated before result import to release its engine memory.

A larger **single-run** check with 32 × 100,000 similar bases took 83.960 s before
and 38.687 s after (2.17×), with identical artifacts. Peak process RSS was
227 MiB before and 261 MiB after. This is recorded separately from the repeated
measurements in the JSON report. Reproduce it with `engine.mjs ENGINE.mjs similar
32 100000` for each engine.

The **128-genome single-run** check (128 × 100,000 similar bases) took
2,040.411 s before and 809.441 s after (**2.52×**). All three artifacts were
byte-identical, and all 128 output genome extents matched their inputs. Peak
process RSS increased from 739.4 to 755.3 MiB (2.2%).
[Raw 128-genome results](../benchmarks/results/engine-128-2026-10-29.json)
include the binary and output hashes. This experimental benchmark does not
change the website's 64-genome input limit.

A follow-up comparison of packed profile scoring and hoisted homology-state
lookup used three alternating fresh-process runs per engine. All artifacts
remained byte-identical. Absolute timings changed between sessions, so compare
the paired measurements within each report:

| Synthetic workload | First optimized engine | Packed-scoring engine | Speedup |
| --- | ---: | ---: | ---: |
| Similar, 12 × 100,000 bases | 4.562 s | 4.134 s | 1.10× |
| Divergent, 4 × 20,000 bases | 1.038 s | 0.970 s | 1.07× |
| Inversions/indels, 4 × 50,000 bases | 0.566 s | 0.540 s | 1.05× |
| Repeats, 4 × 50,000 bases | 0.516 s | 0.495 s | 1.04× |
| Ambiguous bases, 4 × 20,000 bases | 0.252 s | 0.244 s | 1.03× |

[Follow-up measurements](../benchmarks/results/engine-followup-2026-10-29.json)
include both binary hashes, peak process RSS, and Wasm linear-memory capacity.
Linear-memory capacity was unchanged in every case (16–48 MiB); median peak
process RSS changed by −0.9 to +5.1 MiB. The 128-genome run was not repeated for
this follow-up; its earlier result applies to the first optimized binary.

Seed lookup added a further 1–3% improvement across the same five cases, with
identical artifacts and unchanged Wasm heap capacity.
[Seed lookup measurements](../benchmarks/results/engine-seed-2026-10-29.json)
record three alternating runs per engine; 100,096 differential seed cases passed.

A later experiment also packed gap penalties for the dynamic-programming loop.
It preserved outputs but regressed measured runtimes by roughly 1–3%, so it was
not adopted. [Rejected experiment measurements](../benchmarks/results/engine-gap-experiment-2026-10-29.json)
record the comparison against the packed-scoring engine.

A posterior-only HMM backward pass also preserved exact extended-precision
state probabilities in 105 cases and all alignment artifacts. Whole-engine
improvements were small (0–2%); seven paired repetitions of its strongest case
measured only 0.75%. It remains unadopted pending stronger evidence.
[Posterior experiment measurements](../benchmarks/results/engine-posterior-experiment-2026-10-29.json)
include the confirmation runs.

Packed-word copying for multi-child intervals passed 120 bitmap checks,
including partial words, missing rows, and truncation, but whole-engine medians
ranged from 0.5% slower to 0.9% faster. The extra temporary bitmap storage and
code were not justified; the experiment remains unadopted.
[Packed-interval measurements](../benchmarks/results/engine-packed-interval-experiment-2026-10-29.json)
preserve the paired timings and artifact checks.

Specializing the packed scoring loop by nucleotide count sped up its isolated
kernel but did not consistently improve full alignments; it was not adopted.
[Scoring-loop experiment](../benchmarks/results/engine-fixed-profile-experiment-2026-10-29.json)
records both kernel and full-engine timings.

Caching the last genome lookup in hybrid matches was also left out: gains were
inconsistent, two small cases regressed, and a single 32-genome check improved
only 1.6%. [Lookup-cache experiment](../benchmarks/results/engine-hybrid-cache-experiment-2026-10-29.json)
includes 1,059,780 coordinate/orientation checks and the scaling result.
Combining gap-state traceback writes preserved every matrix byte but slowed
full alignments; [those measurements](../benchmarks/results/engine-gap-trace-experiment-2026-10-29.json)
are retained as a rejected experiment.

Inlining the in-memory seed-sort comparator preserved 60 exact ordering cases
and all alignment artifacts, but its initial 0.2–1.6% gains narrowed to 0.3%
in seven paired repetitions of the strongest case. It remains unadopted.
[Seed-sort measurements](../benchmarks/results/engine-sort-inline-experiment-2026-10-29.json)
include the confirmation runs.

Caching the next traceback-row pointer also produced no consistent gain and
was left out. [Traceback-row measurements](../benchmarks/results/engine-trace-row-experiment-2026-10-29.json)
include five workloads and 729 exact traceback-cell checks.

Reusing adjacent match scores likewise passed the traceback checks but gave
mixed timing results, including a slowdown on similar genomes; it was not
adopted. [Match-score measurements](../benchmarks/results/engine-cached-match-experiment-2026-10-29.json)
record the five paired comparisons.

SIMD conversion of gapped strings into bitmap words passed 2,188 kernel and
161 integration cases, including partial words, all byte values, shorter rows,
and missing genomes. Both a temporary-buffer version and a direct-write
version sped up the isolated kernel substantially. Whole-engine gains were
small, however: seven confirmation pairs reduced the strongest apparent gain
to 0.13%, so neither version was adopted.
[Bitmap conversion measurements](../benchmarks/results/engine-gapped-bits-experiment-2026-10-29.json)
include both prototypes and the confirmation runs.

These measurements do not establish speedups or memory capacity for full,
divergent biological genomes or other browser engines.

## Memory and staging

The libc file path replaces POSIX asynchronous I/O inside Emscripten's virtual
filesystem. All staged files and scratch data for a job remain in the worker's
memory until it finishes. Input staging hands fresh Blob buffers directly to
the virtual filesystem, avoiding a second full input copy. After the output
Blobs arrive, the job runner terminates the engine worker before parsing and
saving the alignment, so the engine heap and scratch files need not coexist
with the importer's working set. These changes reduce avoidable memory use;
they do not change the alignment algorithm or its CPU complexity.

Compare input staging and alignment timings in separate Node processes:

```sh
node web/benchmarks/aligner.mjs 12 100000 --copy-inputs
node web/benchmarks/aligner.mjs 12 100000
```

The benchmark reports staging time separately from engine time and includes
process peak RSS (which also includes runtime, engine, and result parsing).
Use repeated runs for timing comparisons; this synthetic input does not
establish performance on divergent genomes.

The in-memory filesystem is the principal scaling limit of this first
port; wasm64, external-memory indexes, and an accelerated anchoring algorithm
need separate parity and performance work. A browser input limit is not a
promise that every input below it will fit in the engine's heap.

## Validation

- C++ kernel tests compare 8,000 profile-score cases bit for bit with the
  original scalar scorer, exercise gapless/gapped coordinate translation on
  both strands across index boundaries, and check single-child interval copying.
  Both packed and scalar fallback paths are exercised. Seed lookup matches the
  original bit-selection loop across 100,096 exhaustive and randomized cases.
  Traceback tests compare exact scores and paths over 729 matrix shapes, tie
  patterns, and terminal-gap modes while exercising cache reuse and growth. Another 75 homology cases
  compare posterior values bit for bit and check final predictions.
- Node regression tests compare all three artifact hashes against the previous
  checked-in engine on five workloads. The fixture records that engine's hash.
- A twelve-genome, 5,000-base synthetic alignment is run by the Node test suite.
- `MAUVE_NATIVE_TESTS=1 web/.venv/bin/python -m pytest web/browser-tests/test_reference.py -q`
  compares an inversion/indel example against the bundled native executable.
  Set `MAUVE_ALIGNER` to override that executable on Linux.
- Browser integration tests run the real engine and exercise cancellation,
  persistence, imports, exports, and repository-relative asset paths.

Broader biological validation and larger/divergent genome benchmarks are still
needed before claiming general scientific parity or capacity at 64 genomes.

## Browser threads

The Pages app selects `static/wasm-threaded` when `crossOriginIsolated` and
`SharedArrayBuffer` are available, with up to eight compute threads, capped by
`navigator.hardwareConcurrency`. Otherwise it selects `static/wasm`. The engine
version, job manifest and log record the selected thread count. This is an upper
bound: short pair lists and the HMM memory heuristic can reduce active workers.

Each threaded job initializes a pool before calling main. `PROXY_TO_PTHREAD`
runs alignment on a pthread so the host worker can service filesystem requests;
`EXIT_RUNTIME` and parent-worker termination release the pool. The safe native OpenMP loops are expressed as bounded C++ pthread jobs in this
build. Independent pairs own their output vectors and TLS slots; recursive gap
searches serialize shared sequence reads. Breakpoint coverage and progress logs
are collected per pair and reduced in serial order. Nested jobs run serially
within their parent team to preserve TLS identity and the worker-pool bound. Shared HMM tables are initialized before starting the team,
including when the first genome pair has no alignment. The HMM team uses the
native 512 MiB estimate; it is a concurrency heuristic, not a total memory cap.
The shared Wasm heap remains capped at 2 GiB, with 8 MiB pthread stacks.

For hosts with header configuration, serve the document and worker scripts with:

```
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: credentialless
```

GitHub Pages uses the root-scoped `isolation-sw.js` included by `build_pages.py`.
It adds these headers to same-origin responses without caching genome data or
intercepting cross-origin API requests. The first visit reloads once after
activation, before workspace initialization. If service workers or isolation
are unavailable, the page continues with the serial engine. Hosts that already
provide isolation headers skip service-worker registration. Use HTTPS or
localhost. See [Emscripten pthread requirements](https://emscripten.org/docs/porting/pthreads.html).

Validation and timing:

```sh
web/.venv/bin/python -m pytest web/browser-tests/test_threaded_browser.py -q
web/.venv/bin/python web/benchmarks/browser-thread-scaling.py --output /tmp/browser-parity.json
web/.venv/bin/python web/benchmarks/browser-thread-scaling.py --genomes 32 --bases 100000 --threads 1 4 8 12 16 --repeats 2 --output /tmp/browser-scaling.json
```

The benchmark launches real Chrome workers with fresh heaps and input files,
checks all three artifact hashes exactly, and includes startup in wall time.
It tests similar, divergent, rearranged, repetitive, ambiguous, and unrelated-first
genomes; the larger mode uses the synthetic similar-genome workload. Browser
tests also exercise the Pages service worker, blocked-service-worker fallback,
and termination of the entire nested worker tree on cancellation.

For a bounded native race check of the browser C++ path on Apple Silicon:

```sh
python3 web/wasm/build_pthread_tsan.py --work /tmp/mauve-wasm-threaded-build --output /tmp/mauve-pthread-tsan
TSAN_OPTIONS=halt_on_error=1 node web/benchmarks/native-parity.mjs /tmp/mauve-pthread-tsan
```

This uses native pthreads and the NEON equivalent of the scoring SIMD operations.
It checks the actual patched C++ pair loop and memory accesses; it does not
instrument the browser's JavaScript runtime. The Playwright tests cover that
integration separately.

### Initial backbone-only result (2026-10-30)

Real Chrome on Apple M4 Max, battery power, 32 synthetic genomes × 100,000 bases,
two alternating runs per configuration, including worker startup and input staging:

| Browser engine | Median wall time |
| --- | ---: |
| Serial | 33.89 s |
| Eight threads | 30.41 s |

The initial backbone-only build reduced runtime by 10.3% (1.11× speedup) on this case.
All XMFA, tree and backbone bytes match. Short workloads gain little and may be
slower from threading overhead. Peak browser memory was not measured. The
[final timing report](../benchmarks/results/browser-threaded-32-scaling-2026-10-30.json)
records binary hashes and individual runs; the
[validation report](../benchmarks/results/browser-threaded-validation-2026-10-30.json)
records the checks and their limits. An initial 1/4/8/12/16-thread sweep found
little improvement above eight threads, so automatic selection stays capped at eight.

The scheduler contract can be tested separately in actual pthread WebAssembly:

```sh
python3 web/wasm/test_kernels.py --work /tmp/mauve-wasm-build --case thread_pool
```

This checks exact iteration coverage, nested thread identity, empty ranges,
exception propagation, and caller TLS restoration. The normal kernel suite
also includes this test. The browser parity harness accepts `--seed-family`
and `--collinear` to exercise alternative alignment modes.

### Additional parallel stages (2026-10-30)

The browser now also parallelizes recursive gap searches, pairwise breakpoint
distances, and seed-occurrence construction. On the same 32 × 100,000-base
synthetic workload in Chrome on Apple M4 Max (battery power), two runs per setting:

| Browser engine | Median wall time |
| --- | ---: |
| Serial | 34.22 s |
| Earlier backbone-only, eight threads | 30.06 s |
| All four stages, eight threads | 29.39 s |

That is 2.2% less time than the earlier threaded build and
14.1% less than serial (1.16× speedup). The reference was rerun
separately after the alternating serial/candidate runs; this is a small timing
sample. All three artifacts match byte for byte across the runs. These gains do
not reproduce the native ARM64 speedup; native-versus-Wasm also changes execution
efficiency, independently of how much work is parallelized.

See the [timing report](../benchmarks/results/browser-full-stages-32-scaling-2026-10-30.json)
and [validation report](../benchmarks/results/browser-full-stages-validation-2026-10-30.json).
The new checks include seed-family and collinear modes, larger native sanitizer
fixtures, and the pthread scheduler contract in both native TSan and WebAssembly.

### Matched stage profiling

`web/benchmarks/profiling/build.py` builds isolated native or threaded browser
engines with identical C++ scope timers. Use the existing prepared native and
threaded checkouts, and separate output directories:

```sh
python3 web/benchmarks/profiling/build.py --target native --work /tmp/mauve-arm64-src --output /tmp/mauve-profile-native
python3 web/benchmarks/profiling/build.py --target browser --work /tmp/mauve-browser-threads --output /tmp/mauve-profile-browser
```

The browser command requires the pinned Emscripten toolchain on PATH. Add
`--mimalloc` for the experimental browser allocator comparison. These builds
must not run concurrently with other builds against the same source checkout.
The wrapper restores instrumented source bytes in a `finally` block and does
not replace production assets. Diagnostic builds are marked with
`STAGE_PROFILE.json`; their normal build manifest alone does not describe the
additional instrumentation or experimental allocator.

Both benchmark harnesses capture `MAUVE_STAGE` records into their JSON reports.
Times are accumulated **inclusive wall milliseconds**, not CPU time. Nested
scopes overlap and must not be summed. For a disjoint top-level breakdown use
`engine - progressive - backbone`, `progressive - alignment_tree`,
`alignment_tree`, and `backbone`. The legacy MUSCLE entry-point counters may be
zero: the Fast variants are included in `gapped_alignment`. The newer function-level
reports also time `RefineFast`, `ProfileAlignFast`, `NWSmall`, `TreeFromMSA`,
`RefineW`, seed occurrence construction, and `SingleCopyDistanceMatrix` separately. Run compilation and timing
sequentially to avoid CPU contention. Exact output hashes must match the
uninstrumented reference before using a profile to guide changes.

The October 30 matched profile (`benchmarks/results/stage-profile-summary-2026-10-30.json`)
uses 32 similar genomes of 100,000 bases at eight threads. Native median process
wall time was 21.60 s (two runs); the default browser allocator took 29.13 s
(four runs). The experimental mimalloc build took 27.76 s median (four runs,
25.26–28.12 s range), a 4.7% runtime reduction. Preparation and alignment/refinement
accounted for about 90% of the native/browser stage gap. Breakpoint-distance time
fell from roughly 0.90 s to 0.19 s with mimalloc. All large-run artifacts match
the existing engine; six small cases also match serial output at eight threads.
This allocator remains diagnostic-only until peak browser memory is evaluated.


### Function profiles and coverage prototype

The detailed results are in
`benchmarks/results/function-profile-findings-2026-10-30.json`. Sampled CPU
profiles were collected in separate runs, using macOS `sample` and Chrome's
worker Profiler via `benchmarks/profiling/browser_cpu.py`. The raw captures are
stored compressed alongside `cpu-profile-summary-2026-10-30.json`; LTO can
attribute an inlined function's samples to its caller. Chrome's first 23 seconds
show the serial main alignment thread busy while most team workers are idle.
This capture covers preparation/refinement rather than the whole job.

`SingleCopyDistanceMatrix` repeatedly sets coverage bits one base at a time.
The diagnostic `--coverage-ranges` build flag uses word-wise range updates when
both aligned rows are entirely ungapped and equally long, retaining the original
column loop for gapped rows. This prototype is confined to the profiling build
wrapper; production build defaults and assets have not been changed.

A power-source change was detected during testing. The final comparison reruns
both variants on AC in baseline/candidate/candidate/baseline order, two runs each,
using 32 similar genomes of 100,000 bases and eight threads:

| Target | Baseline | Coverage prototype | Runtime reduction |
| --- | ---: | ---: | ---: |
| Native ARM64 | 14.76 s | 12.63 s | 14.5% |
| Chrome Wasm | 21.12 s | 17.08 s | 19.1% |

Do not compare these absolute times against earlier battery runs. The harnesses
now record power source before and after each run. No compilation or sampling
ran concurrently with these timing runs. Exact output artifacts match.

`build_kernels.py` and `run_kernels.py` compare isolated native/browser coverage
and dynamic-programming kernels. The AC report is
`benchmarks/results/matched-kernels-ac-2026-10-30.json`. It validates 100 randomized
distance matrices, exhaustive small range boundaries, and exact score/path
checksums. The coverage prototype improves its ungapped microbenchmark by over
100x; that is not an end-to-end speedup. Larger NWSmall matrices take about 1.4x
as long in Chrome. The original isolated coverage microbenchmark is slightly
faster in Chrome, illustrating why a universal Wasm slowdown cannot explain
all full-stage timings. Specific instruction-level attribution remains open.


### Parallel browser refinement windows (2026-10-30)

The production threaded engine now runs independent MUSCLE `RefineW` windows
concurrently. Parameters are copied into worker-local TLS slots without copying
scratch buffers. Each job owns its output MSA; the caller merges windows in
original order, in batches bounded to twice the worker count. The final window
runs on the caller to retain its final MUSCLE state. Progress bookkeeping is
thread-local. Tiny, nested, non-DNA, custom-matrix, and standalone/debug cases
retain the serial path. `MAUVE_PARALLEL_REFINEMENT=0` disables this stage for
native diagnostic runs; the website enables it automatically.

On 32 similar genomes of 100,000 bases, fresh real-Chrome workers on AC power,
two repeats per setting gave:

| Workers | Median wall time |
| --- | ---: |
| 1 (serial engine) | 23.98 s |
| 4 | 15.90 s |
| 8 | 15.34 s |
| 16 | 15.83 s |

Eight workers reduce runtime by 36.0% versus serial and 25.5% versus a fresh
20.60 s control using the preceding threaded engine. The final production binary
also completed in 15.39 s. These are one-workload measurements, not a promise for
all inputs; automatic selection remains capped at eight. All XMFA, tree, and
backbone hashes match. The coverage-range and mimalloc profiling prototypes are
not included in this comparison or production change.

See `benchmarks/results/browser-window-scaling-2026-10-30.json`,
`browser-pre-window-control-2026-10-30.json`, and
`browser-window-validation-2026-10-30.json` for timing and validation details.
