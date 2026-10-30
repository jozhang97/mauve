"""Build an ARM64 macOS progressiveMauve with NEON and bounded OpenMP teams.

Requires Apple clang and an installed libomp (default /opt/homebrew/opt/libomp).
Uses its own --work checkout: do not share it with a WebAssembly build.
"""
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('wasm_build', HERE.parent / 'wasm/build.py')
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


def replace(path, old, new):
    text = path.read_text()
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f'Patch target changed: {path}')
    path.write_text(text.replace(old, new))


def build(root, output, libomp, jobs, sanitize_thread=False):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('This target requires an Apple Silicon Mac.')
    if not (libomp / 'include/omp.h').is_file():
        raise RuntimeError('Install libomp or supply --libomp pointing to it.')
    cc, cxx = os.environ.get('CC', 'clang'), os.environ.get('CXX', 'clang++')
    sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
    if (root / '.mauve-threaded-work').exists() or (root / 'objects-optimized').exists() or (root / 'objects-baseline').exists():
        raise RuntimeError('Use a separate --work directory for native and WebAssembly builds.')
    root.mkdir(parents=True, exist_ok=True)
    (root / '.mauve-native-work').touch()
    boost = shared.prepare_sources(root)
    # Interval iterations update shared bitmaps; keep this loop serial.
    replace(root / 'libMems/libMems/DistanceMatrix.h',
            '#pragma omp parallel for\n\tfor( int ivI',
            '// Shared pair_comp bitmaps require serial interval updates.\n\tfor( int ivI')
    # The shared hash merge is order-sensitive; parallelize independent pairs first.
    replace(root / 'libMems/libMems/ParallelMemHash.cpp',
            '#pragma omp parallel for schedule(dynamic)',
            '// Keep initial match merging deterministic.')
    path = root / 'libMems/libMems/ProgressiveAligner.cpp'
    text = path.read_text()
    begin = text.index('void ProgressiveAligner::CreatePairwiseBPDistance(')
    end = text.index('\ntemplate<', begin)
    part = text[begin:end]
    if 'pair_coverage' not in part:
        part = part.replace('#pragma omp parallel for', 'std::vector<double> pair_coverage(seq_pairs.size());\n#pragma omp parallel for schedule(dynamic)')
        part = part.replace('cur_min_coverage = greedyBreakpointElimination_v4', 'pair_coverage[i] = greedyBreakpointElimination_v4')
        part = part.replace('\t// normalize to [0,1]', '\t// Preserve the serial loop\'s final value without concurrent writes.\n\tif (!pair_coverage.empty()) cur_min_coverage = pair_coverage.back();\n\t// normalize to [0,1]')
        path.write_text(text[:begin] + part + text[end:])

    # Buffer progress text per pair; concurrent ostream formatting mutates cout.
    text = path.read_text()
    begin = text.index('void ProgressiveAligner::CreatePairwiseBPDistance(')
    end = text.index('\ntemplate<', begin)
    part = text[begin:end]
    if 'pair_logs' not in part:
        part = part.replace('std::vector<double> pair_coverage(seq_pairs.size());',
                            'std::vector<double> pair_coverage(seq_pairs.size());\nstd::vector<std::ostringstream> pair_logs(seq_pairs.size());')
        part = part.replace('cout <<', 'pair_logs[i] <<')
        part = part.replace('\t// Preserve the serial loop',
                            '\tfor (const auto& log : pair_logs) cout << log.str();\n\t// Preserve the serial loop')
        path.write_text(text[:begin] + part + text[end:])

    # Cache team identity once per loop iteration, not on every MUSCLE scalar load.
    replace(root / 'muscle/libMUSCLE/threadstorage.h',
            '#define OMP_GET_THREAD_NUM\tomp_get_thread_num()',
            'extern __thread unsigned mauve_thread_index;\n#define OMP_GET_THREAD_NUM mauve_thread_index')
    path = root / 'libMems/libMems/ProgressiveAligner.cpp'
    for loop in ['for(int ni = 0; ni < node_pairs.size(); ni++)',
                 'for(int i = 0; i < seq_pairs.size(); i++)',
                 'for( int seqI = 0; seqI < seq_count; seqI++ )']:
        text = path.read_text()
        # Only the seed-construction loop has this exact preceding pragma.
        target = re.search(r'(#pragma omp parallel for[^\n]*\n\s*' + re.escape(loop) + r'\n\s*\{)', text)
        if target and not text[target.end():].lstrip().startswith('mauve_thread_index ='):
            text = text[:target.end()] + '\n        mauve_thread_index = omp_get_thread_num();' + text[target.end():]
            path.write_text(text)
    # Parallelize complete backbone genome-pair jobs (the inner HMM sees only
    # two genomes here). Each job owns its sorting order and output vectors.
    path = root / 'libMems/libMems/Backbone.cpp'
    text = path.read_text()
    begin = text.index('void makeAllPairwiseGenomeHSS(')
    end = text.index('\nvoid mergePairwiseHomologyPredictions', begin)
    part = text[begin:end]
    if 'process_hmm_pair' not in part:
        start = part.index('\t// make pairwise projections')
        body_start = part.index('\t\t\tvector< uint > projection;', start)
        body_end = part.rindex('\n\t\t}\n\t}\n}')
        body = part[body_start:body_end].replace('iv_ptrs', 'pair_iv_ptrs')
        part = part[:start] + '''
    auto process_hmm_pair = [&](size_t seqI, size_t seqJ) {
        vector<CompactGappedAlignment<>*> pair_iv_ptrs = iv_ptrs;
''' + body + '''
    };
    std::vector<std::pair<size_t,size_t>> hmm_pairs;
    size_t longest = 1;
    for (size_t i = 0; i < seq_count; ++i) {
        longest = std::max(longest, size_t(iv_list.seq_table[i]->length()));
        for (size_t j = i + 1; j < seq_count; ++j) hmm_pairs.push_back(std::make_pair(i,j));
    }
    if (hmm_pairs.empty()) return;
    // Warm legacy HMM statics before any worker accesses them.
    process_hmm_pair(hmm_pairs[0].first, hmm_pairs[0].second);
    const size_t memory_threads = std::max(size_t(1), size_t(512 * 1024 * 1024) / longest / 128);
    const int team = dynamic_cast<const HomologyHmmDetector*>(detector)
        ? int(std::min(size_t(omp_get_max_threads()), memory_threads)) : 1;
#pragma omp parallel for schedule(dynamic) num_threads(team) if(team > 1 && hmm_pairs.size() > 2)
    for (int pair = 1; pair < int(hmm_pairs.size()); ++pair) {
        mauve_thread_index = omp_get_thread_num();
        process_hmm_pair(hmm_pairs[pair].first, hmm_pairs[pair].second);
    }
}
'''
        path.write_text(text[:begin] + part + text[end:])
    # An empty first pair does not execute the HMM. Initialize its shared
    # lookup tables explicitly before any of the later pairs can run.
    replace(path, '// Warm legacy HMM statics before any worker accesses them.',
            '// Initialize HMM statics even when the first pair has no alignment.\n'
            '    getCharmap();\n'
            '    HomologyBaumWelch warm_counts;\n'
            '    HomologyDPTable::getId("homologous");')
    # Native FASTA sources may share seekable streams. Only materialization is
    # serialized; the HMM runs concurrently on job-local strings afterwards.
    path = root / 'libMems/libMems/Islands.h'
    text = path.read_text()
    begin = text.index('void findHssHomologyHMM( const MatchVector&')
    end = text.index('\ntemplate<', begin)
    original = subprocess.check_output(['git', '-C', str(root / 'libMems'), 'show', 'HEAD:libMems/Islands.h'], text=True)
    orig_begin = original.index('void findHssHomologyHMM( const MatchVector&')
    orig_end = original.index('\ntemplate<', orig_begin)
    part = original[orig_begin:orig_end].replace('\t\tGetAlignment( *iv, seq_table, aln_table );',
        '#pragma omp critical(mauve_sequence_read)\n        { GetAlignment( *iv, seq_table, aln_table ); }')
    path.write_text(text[:begin] + part + text[end:])
    # After serial initialization, resetCounts must not write this shared flag.
    replace(root / 'libMems/libMems/HomologyHMM/homology.cc',
            '    bInited = true;', '    if (!bInited) bInited = true;')

    def sources(folder, key):
        text = (folder / 'Makefile.am').read_text().replace('\\\n', ' ')
        return [folder / f for f in re.search(r'^' + key + r'\s*=([^\n]+)', text, re.M)[1].split()]
    files = sources(root / 'libGenome/libGenome', 'LIBGENOME_SRC') + sources(root / 'muscle/libMUSCLE', 'LIBMUSCLE_SRC')
    for key in ['LIBMEMS_SRC', 'HOMOLOGYHMM_SRC', 'DMSML_SRC']:
        files += sources(root / 'libMems/libMems', key)
    files += [root / 'mauveAligner/src' / f for f in ['progressiveMauve.cpp', 'UniqueMatchFinder.cpp']]
    files += list((boost / 'libs/filesystem/src').glob('*.cpp')) + [boost / 'libs/system/src/error_code.cpp', boost / 'libs/iostreams/src/mapped_file.cpp']
    files += [shared.HERE / 'optimizations/profile_row.cpp', shared.HERE / 'optimizations/seed_lookup.cpp', HERE / 'main.cpp']
    flags = ['-isysroot', sdk, '-O3', '-flto', '-DNDEBUG', '-D_LIB', '-DUSE_LIBC', '-DBOOST_NO_CXX11_SCOPED_ENUMS',
             '-ffp-contract=off', '-Xpreprocessor', '-fopenmp', '-I' + str(libomp / 'include'),
             '-I' + str(HERE / 'include'), '-I' + str(shared.HERE / 'optimizations'),
             '-Wno-deprecated-declarations', '-Wno-register', '-Wno-inconsistent-missing-override', '-Wno-c++11-narrowing',
             '-DMAUVE_PROFILE_ROWS', '-DMAUVE_FAST_TRANSLATE', '-DMAUVE_SEED_LOOKUP', '-DMAUVE_COMPACT_TRACE',
             '-DMAUVE_LAZY_TRACE', '-DMAUVE_ROW_GAPS', '-DMAUVE_LOCAL_D_SCORE']
    flags += ['-I' + str(root / f) for f in ['libGenome', 'muscle', 'libMems', 'boost_1_65_1']]
    if sanitize_thread:
        flags = [f for f in flags if f not in ['-O3', '-flto']] + ['-O1', '-g', '-fsanitize=thread', '-fno-omit-frame-pointer']
    obj = root / ('objects-native-tsan' if sanitize_thread else 'objects-native'); obj.mkdir(exist_ok=True)
    def compile_one(file):
        dest = obj / (hashlib.sha256(str(file).encode()).hexdigest()[:16] + '.o')
        extra = ['-Wno-error=implicit-function-declaration'] if file.suffix == '.c' else ['-std=c++14']
        if file.name == 'progressiveMauve.cpp':
            extra += ['-Dmain=mauve_main']
        subprocess.run([cc if file.suffix == '.c' else cxx, *flags, *extra, '-c', str(file), '-o', str(dest)], check=True)
        return dest
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        objects = list(pool.map(compile_one, files))
    output.mkdir(parents=True, exist_ok=True)
    executable = output / 'progressiveMauve'
    link_flags = ['-fsanitize=thread'] if sanitize_thread else ['-flto']
    subprocess.run([cxx, *map(str, objects), '-isysroot', sdk, '-O3', *link_flags, '-L' + str(libomp / 'lib'), '-Wl,-rpath,' + str(libomp / 'lib'), '-lomp', '-o', str(executable)], check=True)
    for name in ['libGenome', 'muscle', 'mauveAligner']:
        shutil.copyfile(root / name / 'COPYING', output / (name + '-COPYING'))
    shutil.copyfile(root / 'libMems/LICENSE', output / 'libMems-LICENSE')
    shutil.copyfile(boost / 'LICENSE_1_0.txt', output / 'Boost-LICENSE')
    manifest = {'target': 'arm64-macos', 'compiler': subprocess.check_output([cxx, '--version'], text=True),
                'sources': shared.PINS, 'libomp': str(libomp), 'max_threads': 16, 'default_threads': 'min(8, available processors)',
                'sdk': sdk, 'flags': flags, 'sanitizer': 'thread' if sanitize_thread else None,
                'local_sources': {str(p.relative_to(HERE.parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [HERE / 'build.py', HERE / 'main.cpp', HERE / 'include/wasm_simd128.h', shared.HERE / 'build.py', *sorted((shared.HERE / 'optimizations').glob('*'))] if p.is_file()},
                'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest()}
    (output / 'SOURCES.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--libomp', type=Path, default=Path('/opt/homebrew/opt/libomp'))
    p.add_argument('--jobs', type=int, default=8)
    p.add_argument('--sanitize-thread', action='store_true')
    a = p.parse_args()
    if a.jobs < 1:
        p.error('--jobs must be positive')
    build(a.work.resolve(), a.output.resolve(), a.libomp.resolve(), a.jobs, a.sanitize_thread)
