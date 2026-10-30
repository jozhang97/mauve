"""Pthread parallelism for independent genome pairs and seed construction."""
import subprocess
import re


def replace(path, old, new):
    text = path.read_text()
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f'Patch target changed: {path}')
    path.write_text(text.replace(old, new))


def prepare_threads(root):
    replace(root / 'muscle/libMUSCLE/threadstorage.h',
            '#ifdef _OPENMP',
            '#ifdef __EMSCRIPTEN_PTHREADS__\n#define MAX_THREAD_COUNT 16\nextern thread_local unsigned mauve_thread_index;\n#define OMP_GET_THREAD_NUM mauve_thread_index\n#elif defined(_OPENMP)')
    for file in ['Backbone.cpp', 'Islands.h', 'ProgressiveAligner.cpp']:
        path = root / 'libMems/libMems' / file
        text = path.read_text()
        if '#include "thread_pool.h"' not in text:
            path.write_text('#include "thread_pool.h"\n' + text)
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
        ? int(std::min(size_t(mauve_thread_count()), memory_threads)) : 1;
    mauve_parallel_pairs(hmm_pairs.size(), team, [&](size_t pair) {
        process_hmm_pair(hmm_pairs[pair].first, hmm_pairs[pair].second);
    });
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
        '        { std::lock_guard<std::mutex> lock(mauve_sequence_mutex()); GetAlignment( *iv, seq_table, aln_table ); }')
    path.write_text(text[:begin] + part + text[end:])
    # After serial initialization, resetCounts must not write this shared flag.
    replace(root / 'libMems/libMems/HomologyHMM/homology.cc',
            '    bInited = true;', '    if (!bInited) bInited = true;')


    prepare_alignment_threads(root)
    prepare_refinement_threads(root)


def parallel_loop(part, variable, bound):
    """Replace one pinned OpenMP loop with a bounded pthread lambda."""
    marker = f'mauve_parallel_for({bound}, [&](size_t {variable})'
    if marker in part:
        return part
    pattern = r'#pragma omp parallel for[^\n]*\n\s*for\(\s*int ' + variable + r' = 0; ' + variable + r' < ' + re.escape(bound) + r'; ' + variable + r'\+\+\s*\)\s*\{'
    match = re.search(pattern, part)
    if not match:
        raise RuntimeError('Parallel loop target changed: ' + variable)
    # Ignore braces in comments and literals while finding the loop's end.
    tokens = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]')
    depth = 1
    for token in tokens.finditer(part, match.end()):
        if token[0] == '{': depth += 1
        elif token[0] == '}': depth -= 1
        if depth == 0:
            body = part[match.end():token.start()]
            if variable == 'ni':
                body = body.replace('continue;\t// no sense searching one isn\'t defined!', 'return;\t// no sense searching one isn\'t defined!')
            return part[:match.start()] + marker + ' {' + body + '});' + part[token.end():]
    raise RuntimeError('Unclosed parallel loop: ' + variable)


def prepare_alignment_threads(root):
    path = root / 'libMems/libMems/ProgressiveAligner.cpp'
    text = path.read_text()
    begin = text.index('void ProgressiveAligner::CreatePairwiseBPDistance(')
    end = text.index('\ntemplate<', begin)
    part = text[begin:end]
    if 'pair_coverage' not in part:
        part = part.replace('#pragma omp parallel for', 'std::vector<double> pair_coverage(seq_pairs.size());\nstd::vector<std::ostringstream> pair_logs(seq_pairs.size());\n#pragma omp parallel for')
        part = part.replace('cur_min_coverage = greedyBreakpointElimination_v4', 'pair_coverage[i] = greedyBreakpointElimination_v4')
        part = part.replace('cout <<', 'pair_logs[i] <<')
        part = part.replace('\t// normalize to [0,1]', '\tfor (const auto& log : pair_logs) cout << log.str();\n\tif (!pair_coverage.empty()) cur_min_coverage = pair_coverage.back();\n\t// normalize to [0,1]')
    part = parallel_loop(part, 'i', 'seq_pairs.size()')
    text = text[:begin] + part + text[end:]
    text = parallel_loop(text, 'ni', 'node_pairs.size()')
    text = parallel_loop(text, 'seqI', 'seq_count')
    path.write_text(text)
    # Recursive gap searches can read the same underlying FASTA stream.
    replace(path,
        'new_seq = new gnSequence( r_list.seq_table[ seqI ]->ToString( diff, gap_start ) );',
        '{ std::lock_guard<std::mutex> lock(mauve_sequence_mutex());\n'
        '            new_seq = new gnSequence( r_list.seq_table[ seqI ]->ToString( diff, gap_start ) ); }')


def prepare_refinement_threads(root):
    """Parallelize independent MUSCLE windows with bounded temporary outputs."""
    folder = root / 'muscle/libMUSCLE'
    path = folder / 'params.cpp'
    text = path.read_text()
    if 'mauve_muscle_settings_snapshot()' not in text:
        # These are the pinned parameter declarations, not internal TLS caches.
        names = list(dict.fromkeys(re.findall(r'^TLS<[^>]+> (g_\w+)', text, re.M)))
        if len(names) < 90:
            raise RuntimeError('MUSCLE parameter declarations changed')
        capture = '\n'.join(f'    const auto saved_{name} = {name}.get();' for name in names)
        restore = '\n'.join(f'        {name}.get() = saved_{name};' for name in names)
        text += '\nnamespace muscle {\nstd::function<void()> mauve_muscle_settings_snapshot() {\n' + capture + '\n    return [=]() {\n' + restore + '\n    };\n}\n}\n'
        path.write_text('#include "muscle_window_settings.h"\n' + text)
    # These progress fields were the remaining shared mutable MUSCLE globals.
    # Each actual pthread owns its progress state; alignment caches use the
    # scheduler's stable TLS slots instead.
    path = folder / 'progress.cpp'
    text = path.read_text()
    if 'static thread_local unsigned g_uIter' not in text:
        text = re.sub(r'\bstatic (?=(?:unsigned|FILE|char|time_t|bool|int|double)\b)', 'static thread_local ', text)
        path.write_text(text)
    path = folder / 'refinew.cpp'
    original = subprocess.check_output(['git', '-C', str(root / 'muscle'), 'show', 'HEAD:libMUSCLE/refinew.cpp'], text=True)
    start = original.index('\t\tconst unsigned uColFrom =', original.index('void RefineW('))
    end = original.index('\n\t\tif (uWindowIndex == g_uSaveWindow.get())', start)
    body = original[start:end]
    # Empty windows must not dereference vr[0]. They contribute no columns.
    body = body.replace('vr.size() > 1 ? msaTmp.GetColCount() : vr[0]->size()', 'vr.size() > 1 ? msaTmp.GetColCount() : (vr.empty() ? 0 : vr[0]->size())')
    marker = '\tfor (unsigned uWindowIndex = g_uWindowFrom.get(); uWindowIndex <= g_uWindowTo.get(); ++uWindowIndex)'
    parallel = '''
    // MAUVE_PARALLEL_REFINEMENT: jobs own their MSA and scratch state; only the
    // caller appends completed windows, in original order. Retain the serial
    // path for tiny jobs, nested teams, and MUSCLE's standalone/debug modes.
    const unsigned firstWindow = g_uWindowFrom.get();
    const unsigned lastWindow = g_uWindowTo.get();
    const char* parallelSetting = std::getenv("MAUVE_PARALLEL_REFINEMENT");
    if (mauve_thread_count() > 1 && !mauve_in_parallel &&
        (!parallelSetting || std::atoi(parallelSetting) != 0) &&
        g_SeqType.get() == SEQTYPE_DNA && g_uMaxIters.get() == 1 &&
        g_bQuiet.get() && !g_bVerbose.get() && g_uSaveWindow.get() == uInsane &&
        g_uWindowOffset.get() == 0 && uColCount > 0 && lastWindow < uWindowCount &&
        lastWindow >= firstWindow &&
        lastWindow - firstWindow >= 7 && g_pstrMatrixFileName.get() == 0) {
        const auto restoreSettings = mauve_muscle_settings_snapshot();
        const auto weightMethod = GetSeqWeightMethod();
        const unsigned windowWidth = g_uRefineWindow.get();
        auto processWindow = [&](unsigned uWindowIndex, MSA& msaOut) {
            restoreSettings();
            SetAlpha(ALPHA_DNA);
            SetSeqWeightMethod(weightMethod);
            SetMaxIters(g_uMaxIters.get());
            MSA::SetIdCount(uSeqCount);
            msaOut.SetSize(uSeqCount, windowWidth + windowWidth / 5);
            for (unsigned s = 0; s < uSeqCount; ++s) {
                msaOut.SetSeqName(s, msaIn.GetSeqName(s));
                msaOut.SetSeqId(s, msaIn.GetSeqId(s));
            }
''' + body + '''
        };
        const unsigned batchSize = 2 * mauve_thread_count();
        for (unsigned begin = firstWindow; begin < lastWindow; ) {
            const unsigned count = std::min(batchSize, lastWindow - begin);
            std::vector<std::unique_ptr<MSA>> results(count);
            for (auto& result : results) result.reset(new MSA);
            mauve_parallel_for(count, [&](size_t i) { processWindow(begin + i, *results[i]); });
            MSA::SetIdCount(uSeqCount);
            for (const auto& result : results) AppendMSA(msaOut, *result);
            begin += count;
        }
        // Preserve the caller's final MUSCLE state by running the last window
        // on the caller, just as the original ordered loop did.
        MSA last;
        processWindow(lastWindow, last);
        AppendMSA(msaOut, last);
        return;
    }
'''
    if original.count(marker) != 1:
        raise RuntimeError('MUSCLE refinement loop changed')
    path.write_text('#include "thread_pool.h"\n#include "muscle_window_settings.h"\n#include <memory>\n' + original.replace(marker, parallel + marker))
