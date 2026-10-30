# Apple Silicon multicore engine

This target runs progressiveMauve as a native ARM64 process with NEON scoring and
OpenMP genome-pair workers. It is used by the **local Python server**, not the
standalone GitHub Pages website. The website uses its separate
[WebAssembly pthread engine](../wasm/README.md#browser-threads) when shared memory
is available, with a serial fallback.

## Build and run

Requires Xcode command-line tools and an installed `libomp` (normally
`/opt/homebrew/opt/libomp`). The build does not install system packages. It uses
the same pinned upstream revisions and scoring optimizations as the browser.
Use a separate work directory from the WebAssembly build.

```sh
python3 web/native/build.py --work /tmp/mauve-native-build --output web/native/bin
MAUVE_THREADS=8 ./web/run.sh
```

On an ARM64 Mac, the local server selects `web/native/bin/progressiveMauve` when
present and executable. Explicit `MAUVE_ALIGNER` configuration or an executable
on `PATH` still takes precedence. Restart an existing server to change engines.
The local web job form retains its existing eight-genome input limit; the
32-genome benchmark invokes the native executable directly.
The generated binary and its manifest are ignored by Git; rebuild on the target
Mac so the SDK and OpenMP library match that machine.

`MAUVE_THREADS` accepts integers from **1 through 16**. The default is the smaller
of eight and the available CPU count. This controls the maximum team size, not
a promise to keep that many cores busy: substantial progressive-alignment work
remains serial. Nested parallel teams are disabled because the legacy scratch
arrays have 16 thread slots. Idle workers sleep by default (`OMP_WAIT_POLICY=PASSIVE`);
an explicit environment setting takes precedence.

## Parallel work and correctness

- Existing independent recursive-pair, breakpoint-distance, and seed-occurrence
  loops run in OpenMP teams. Team indices are cached at loop entry to avoid
  repeatedly querying OpenMP inside scalar scoring operations.
- Backbone homology work runs over complete genome-pair jobs. Each job has its
  own sorting vector and result vectors. Shared native sequence reads are
  serialized; HMM calculations use local strings outside that lock.
- A first serial pair initializes legacy HMM tables before worker access. A
  repeated shared initialization-flag write was removed.
- Pairwise coverage values and progress messages are collected per job and
  combined in serial order. The legacy interval loop that writes shared
  bitmaps, and the order-sensitive initial match-merging loop, remain serial.
- HMM concurrency is reduced for large inputs using a conservative estimate of
  128 scratch bytes per longest-input base and a 512 MiB budget. This is a
  concurrency heuristic, **not a hard bound on process memory**.
- Floating-point contraction is disabled. The NEON adapter implements the same
  separate multiply/add operations as the Wasm scoring kernel.

## Validation and benchmarking

```sh
python3 web/native/test_kernels.py --work /tmp/mauve-native-build
node web/benchmarks/native-parity.mjs web/native/bin/progressiveMauve --full
python3 web/benchmarks/native-scaling.py --engine web/native/bin/progressiveMauve \
  --threads 1 2 4 8 16 --repeats 3 --output /tmp/native-scaling.json
PYTHONPATH=web MAUVE_NATIVE_TESTS=1 web/.venv/bin/python -m pytest \
  web/tests/test_jobs.py -k real_progressivemauve -q
```

The parity check normalizes only input-file path fields in XMFA, then compares
alignment, guide-tree, and backbone bytes against the shipped browser engine.
Scaling checks require exact, unnormalized hashes across every thread count and
repetition. Each run uses a fresh process and removes generated input indexes.
Wall timings include native process startup; peak RSS covers the native process.

For race detection, build with `--sanitize-thread` and run with a compatible
ThreadSanitizer runtime and LLVM Archer. Archer supplies the OpenMP synchronization
annotations needed to avoid false barrier reports; see [LLVM's Archer documentation](https://openmp.llvm.org/doxygen/dir_d25e7fcf0ab543d5b35a958546f34a9d.html).
`CC` and `CXX` select the compilers for this optional build. On the development
Mac, the Xcode sanitizer runtime crashed even on an empty program; the newer
Command Line Tools runtime worked. Example after building Archer separately:

```sh
CC=/Library/Developer/CommandLineTools/usr/bin/clang \
CXX=/Library/Developer/CommandLineTools/usr/bin/clang++ \
python3 web/native/build.py --work /tmp/mauve-native-build \
  --output /tmp/mauve-native-tsan --sanitize-thread
OMP_TOOL_LIBRARIES=/path/to/libarcher.dylib \
TSAN_OPTIONS=halt_on_error=1:ignore_noninstrumented_modules=1 \
node web/benchmarks/native-parity.mjs /tmp/mauve-native-tsan/progressiveMauve
```

The sanitizer build is for testing only. Passing these checks is not a proof of
race freedom or scientific parity on all biological datasets.

## Measurements on the development M4 Max

For 32 similar synthetic genomes of 100,000 bases each:

| Engine | Runtime | Peak native RSS | Runs |
| --- | --- | --- | --- |
| Current browser Wasm | 33.77 s | — | 1 |
| Native ARM64, 1 thread | 27.92 s | 120.5 MiB | 2 |
| Native ARM64, 4 threads | 22.86 s | 171.9 MiB | 2 |
| Native ARM64, 8 threads | 21.76 s | 210.3 MiB | 2 |
| Native ARM64, 16 threads | 22.07 s | 280.4 MiB | 2 |

Native values are medians of ascending/descending thread-count runs. The
separate native-then-Wasm parity run took 21.77 versus 33.77 seconds (1.55×).
Native timings include process startup; Wasm timing excludes module loading and
input staging. All runs used battery power. These are synthetic partial genomes,
not complete biological genomes. Native threading saves about 22% of the
single-thread native runtime on this workload, while increasing memory.

[Thread scaling](../benchmarks/results/native-arm64-32-scaling-2026-10-29.json),
[fresh browser comparison](../benchmarks/results/native-arm64-browser-32-2026-10-29.json),
and [five-workload medians](../benchmarks/results/native-arm64-scaling-2026-10-29.json)
include raw timings and engine hashes. On the 12-genome similar case, 1/8/16
threads took 4.52/3.97/3.94 seconds across three runs each. Smaller four-genome
cases gained little from threading; eight is the default to balance scaling
and memory, not a claim that it is optimal for every input.

Final validation: 40 Node tests, 26 server/browser/build tests, and one real
native-server job passed; two optional tests were skipped. Native kernel checks
passed 8,000 bit-exact scoring cases and 100,096 seed cases. ThreadSanitizer plus
Archer passed all five 4 × 5,000-base fixtures and a 12 × 20,000-base case at eight
threads. The sanitized 12 × 100,000-base case exceeded its 60-second budget;
normal full-size parity passed. See the [validation record](../benchmarks/results/native-arm64-validation-2026-10-29.json).
