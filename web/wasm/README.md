# progressiveMauve in WebAssembly

The checked-in `mauve_web/static/wasm/progressiveMauve.{mjs,wasm}` runs the actual
progressiveMauve algorithm, including libMems, libGenome and MUSCLE. It is not a
pairwise alignment substitute. Each job gets a new worker and Emscripten instance;
terminating that worker cancels computation and releases its memory.

## Rebuild

Install/activate [Emscripten 4.0.15](https://emscripten.org/docs/getting_started/downloads.html)
in a separate directory, then run:

```sh
source /path/to/emsdk/emsdk_env.sh
python3 web/wasm/build.py --work /tmp/mauve-wasm-build --jobs 4
node --test web/browser-tests/wasm.test.mjs
```

Python 3.11.8+ (tar extraction filters), Git, and the Emscripten SDK are build
requirements. A static release needs none of them on the visitor's machine.
`build.py` pins all four upstream Git revisions and verifies the Boost 1.65.1
archive SHA-256. It compiles all sources, including dependencies, on each run.
The script is also included in the Pages artifact beside the binaries and
licenses; `SOURCES.json` records their source URLs/revisions.

The compatibility changes are intentionally small and applied by the script:

- Include Boost's workaround macro header explicitly.
- Match libc++'s `std::swap` exception specification.
- Implement the upstream libc file-size branches using `stat`.

No alignment/scoring heuristic was changed. The build uses `-O3 -msimd128`,
C++ exception support, an 8 MiB stack, and growable wasm32 memory capped at 2 GiB.
It does not use fast-math or OpenMP. SIMD lets the browser use its native vector
instructions, including on Apple Silicon. The current aligner runs on one CPU
worker; WebGPU accelerates viewer identity scans, not progressiveMauve itself.

The libc file path replaces POSIX asynchronous I/O inside Emscripten's virtual
filesystem. All staged files and scratch data for a job remain in the worker's
memory until it finishes. This is the principal scaling limit of this first
port; wasm64, external-memory indexes, and an accelerated anchoring algorithm
need separate parity and performance work. A browser input limit is not a
promise that every input below it will fit in the engine's heap.

## Validation

- A twelve-genome, 5,000-base synthetic alignment is run by the Node test suite.
- `MAUVE_NATIVE_TESTS=1 web/.venv/bin/python -m pytest web/browser-tests/test_reference.py -q`
  compares an inversion/indel example against the bundled native executable.
  Set `MAUVE_ALIGNER` to override that executable on Linux.
- Browser integration tests run the real engine and exercise cancellation,
  persistence, imports, exports, and repository-relative asset paths.

Broader biological validation and larger/divergent genome benchmarks are still
needed before claiming general scientific parity or capacity at 64 genomes.
