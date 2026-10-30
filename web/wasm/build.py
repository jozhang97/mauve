"""Rebuild progressiveMauve with Emscripten 4.0.15 (emcc/em++ must be on PATH).
Pinned upstream sources are downloaded into --work; no system packages change.
"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request

PINS = {
    'mauveAligner': '3e8293836119a8a6cc883b48f234947cf55387c5',
    'libMems': '1f067601ae48f898dc3c9b92a3b7bf636d04fc70',
    'libGenome': '41b5c8bc02048f41dbd0d1e116b3bca8b4a384db',
    'muscle': 'ec6ab52e7a667e9d2fa70e89b3d2d9adb81f074e',
}
BOOST_SHA256 = '9807a5d16566c57fd74fb522764e0b134a8bbe6b6e8967b83afefd30dcd3be81'
HERE = Path(__file__).resolve().parent


def build(root, output, workers, baseline=False, profiling=False):
    version = subprocess.check_output(['emcc', '--version'], text=True)
    if '4.0.15' not in version:
        raise RuntimeError('Use Emscripten 4.0.15 for this pinned build.')
    root.mkdir(parents=True, exist_ok=True)
    for name, revision in PINS.items():
        dest = root / name
        if not dest.exists():
            subprocess.run(['git', 'clone', 'https://github.com/koadman/' + name + '.git', str(dest)], check=True)
        actual = subprocess.check_output(['git', '-C', str(dest), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != revision:
            subprocess.run(['git', '-C', str(dest), 'checkout', '--detach', revision], check=True)
    boost = root / 'boost_1_65_1'
    if not boost.exists():
        archive = root / 'boost.tar.bz2'
        urllib.request.urlretrieve('https://archives.boost.io/release/1.65.1/source/boost_1_65_1.tar.bz2', archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != BOOST_SHA256:
            raise RuntimeError('Boost checksum mismatch')
        with tarfile.open(archive) as tar:
            tar.extractall(root, filter='data')
    # Minimal compatibility fixes; alignment/scoring algorithms are unchanged.
    def patch(path, old, new):
        source = path.read_text()
        if new in source:
            return
        if old in source:
            path.write_text(source.replace(old, new))
        else:
            raise RuntimeError('Patch target changed: ' + str(path))
    patch(boost / 'boost/type_traits/remove_pointer.hpp', '#include <boost/config.hpp>\n\n',
          '#include <boost/config.hpp>\n#include <boost/config/workaround.hpp>\n\n')
    path = root / 'libMems/libMems/CompactGappedAlignment.h'
    patch(path, 'void swap( mems::CompactGappedAlignment<>& a, mems::CompactGappedAlignment<>& b )\n',
          'void swap( mems::CompactGappedAlignment<>& a, mems::CompactGappedAlignment<>& b ) noexcept(is_nothrow_move_constructible<mems::CompactGappedAlignment<>>::value && is_nothrow_move_assignable<mems::CompactGappedAlignment<>>::value)\n')
    path = root / 'libMems/libMems/dmSML/asyncio.c'
    patch(path, '#include <string.h>\n\n', '#include <string.h>\n#include <sys/stat.h>\n\n')
    source = path.read_text()
    if '#error "libc aStatSize not implemented"' in source:
        source = source.replace('#error "libc aStatSize not implemented"', 'struct stat data; return stat(path, &data) ? 0 : data.st_size;', 1)
        source = source.replace('#error "libc aStatSize not implemented"', 'return aStatFileSize(path) / sizeof(record_t);', 1)
        path.write_text(source)
    # Keep the upstream scalar path available for reproducible A/B comparisons.
    path = root / 'muscle/libMUSCLE/nwsmall.cpp'
    patch(path, '#include "libMUSCLE/profile.h"',
          '#include "libMUSCLE/profile.h"\n#include "mauve_profile_row.h"')
    scalar_row = ('\t\tfor (unsigned j = 1; j < uLengthB; ++j)\n'
                  '\t\t\tMNext[j+1] = ScoreProfPos2(PA[i], PB[j]);')
    row_dispatch = ('#ifdef MAUVE_PROFILE_ROWS\n'
                    '\t\tScoreProfPos2Row(PA[i], PB + 1, uLengthB - 1, MNext + 2);\n'
                    '#else\n' + scalar_row + '\n#endif')
    # The replacement contains the original loop, so check the marker first.
    if '#ifdef MAUVE_PROFILE_ROWS' not in path.read_text():
        patch(path, scalar_row, row_dispatch)
    patch(path, '\tSetTermGaps(PB, uLengthB);\n',
          '\tSetTermGaps(PB, uLengthB);\n'
          '#ifdef MAUVE_PROFILE_ROWS\n'
          '\tconst PackedProfileRows packedScores(PB + 1, uLengthB - 1, uLengthA >= 8);\n'
          '#endif\n')
    patch(path, '\t\tScoreProfPos2Row(PA[i], PB + 1, uLengthB - 1, MNext + 2);',
          '\t\tpackedScores.score(PA[i], MNext + 2);')
    # These penalties are constant across a DP row. Explicitly load them once
    # because writes through score/trace pointers can inhibit alias analysis.
    gap_macros = '''#ifdef MAUVE_ROW_GAPS
#define ROW_GAP_OPEN(i) gapOpenA
#define ROW_GAP_CLOSE(i) gapCloseA
#else
#define ROW_GAP_OPEN(i) PA[i-1].m_scoreGapOpen
#define ROW_GAP_CLOSE(i) PA[i-1].m_scoreGapClose
#endif

'''
    patch(path, '#define RECURSE_D(i, j)', gap_macros + '#define RECURSE_D(i, j)')
    patch(path, 'MPrev[j] + PA[i-1].m_scoreGapOpen', 'MPrev[j] + ROW_GAP_OPEN(i)')
    if 'CURRENT_D_SCORE(j) + ROW_GAP_CLOSE(i)' not in path.read_text():
        patch(path, 'DRow[j] + PA[i-1].m_scoreGapClose', 'DRow[j] + ROW_GAP_CLOSE(i)')
    patch(path, '// Main DP loop', '#ifdef MAUVE_ROW_GAPS\n'
          '\tSCORE gapOpenA = 0, gapCloseA = 0;\n#endif\n// Main DP loop')
    patch(path, '\t\tchar *TBRow = TB[i];', '\t\tchar *TBRow = TB[i];\n'
          '#ifdef MAUVE_ROW_GAPS\n'
          '\t\tgapOpenA = PA[i-1].m_scoreGapOpen;\n'
          '\t\tgapCloseA = PA[i-1].m_scoreGapClose;\n#endif')
    patch(path, '// Special case for i=uLengthA', '#ifdef MAUVE_ROW_GAPS\n'
          '\tgapOpenA = PA[uLengthA-1].m_scoreGapOpen;\n#endif\n'
          '// Special case for i=uLengthA')
    # Keep the current deletion score across traceback-byte writes, which can
    # otherwise force a reload through DRow before the M recurrence.
    deletion_macros = '''#ifdef MAUVE_LOCAL_D_SCORE
#define STORE_D_SCORE(j, value) DRow[j] = Dij = (value)
#define CURRENT_D_SCORE(j) Dij
#else
#define STORE_D_SCORE(j, value) DRow[j] = (value)
#define CURRENT_D_SCORE(j) DRow[j]
#endif

'''
    gap_marker = '#ifdef MAUVE_ROW_GAPS\n#define ROW_GAP_OPEN(i)'
    patch(path, gap_marker, deletion_macros + gap_marker)
    patch(path, 'DRow[j] = DD;', 'STORE_D_SCORE(j, DD);')
    patch(path, 'DRow[j] = MD;', 'STORE_D_SCORE(j, MD);')
    patch(path, 'SCORE DM = DRow[j] + ROW_GAP_CLOSE(i);',
          'SCORE DM = CURRENT_D_SCORE(j) + ROW_GAP_CLOSE(i);')
    patch(path, '\tSCORE Iij = MINUS_INFINITY;', '#ifdef MAUVE_LOCAL_D_SCORE\n'
          '\tSCORE Dij = 0;\n#endif\n\tSCORE Iij = MINUS_INFINITY;')
    # Keep traceback cells contiguous and avoid a 1024-by-1024 minimum cache.
    path = root / 'muscle/libMUSCLE/nwsmall.cpp'
    patch(path, 'static TLS<char **> CacheTB;',
          'static TLS<char **> CacheTB;\n'
          '#ifdef MAUVE_COMPACT_TRACE\nstatic TLS<char *> CacheTBData;\n#endif')
    free_rows = ('\tfor (unsigned i = 0; i < uCachePrefixCountA.get(); ++i)\n'
                 '\t\tdelete[] CacheTB.get()[i];')
    patch(path, free_rows, '#ifdef MAUVE_COMPACT_TRACE\n'
          '\tdelete[] CacheTBData.get();\n#else\n' + free_rows + '\n#endif')
    growth = ('\tuCachePrefixCountA.get() = MaxA + 1024;\n'
              '\tuCachePrefixCountB.get() = MaxB + 1024;')
    patch(path, growth, '#ifdef MAUVE_COMPACT_TRACE\n'
          '\tuCachePrefixCountA.get() = MaxA + 64;\n'
          '\tuCachePrefixCountB.get() = MaxB + 64;\n#else\n' + growth + '\n#endif')
    alloc_rows = ('\tfor (unsigned i = 0; i < uCachePrefixCountA.get(); ++i)\n'
                  '\t\tCacheTB.get()[i] = new char [uCachePrefixCountB.get()];')
    patch(path, alloc_rows, '#ifdef MAUVE_COMPACT_TRACE\n'
          '\tconst size_t rows = uCachePrefixCountA.get(), columns = uCachePrefixCountB.get();\n'
          '\tif (columns && rows > size_t(-1) / columns) Quit("Traceback cache exceeds addressable memory");\n'
          '\tCacheTBData.get() = new char[rows * columns];\n'
          '\tfor (unsigned i = 0; i < uCachePrefixCountA.get(); ++i)\n'
          '\t\tCacheTB.get()[i] = CacheTBData.get() + size_t(i) * columns;\n'
          '#else\n' + alloc_rows + '\n#endif')
    # Interior M cells are written before their D/I flags are used. Assigning
    # all flags on that first write avoids clearing the entire traceback grid.
    trace_macros = '''#ifdef MAUVE_LAZY_TRACE
#define INIT_M_TRACE(TB, i, j) ((void)0)
#define WRITE_M_TRACE(TB, i, j, value) TB[i+1][j+1] = (value)
#else
#define INIT_M_TRACE(TB, i, j) TB[i+1][j+1] &= ~BIT_xM
#define WRITE_M_TRACE(TB, i, j, value) TB[i+1][j+1] |= (value)
#endif

'''
    patch(path, '#define RECURSE_M(i, j)', trace_macros + '#define RECURSE_M(i, j)')
    patch(path, '\tTB[i+1][j+1] &= ~BIT_xM;', '\tINIT_M_TRACE(TB, i, j);')
    for bits in ['BIT_MM', 'BIT_DM', 'BIT_IM']:
        patch(path, '\t\tTB[i+1][j+1] |= ' + bits + ';',
              '\t\tWRITE_M_TRACE(TB, i, j, ' + bits + ');')
    clear_grid = ('\tfor (unsigned i = 0; i < uPrefixCountA; ++i)\n'
                  '\t\tmemset(TB[i], 0, uPrefixCountB);')
    patch(path, clear_grid, '#ifdef MAUVE_LAZY_TRACE\n'
          '\t// First two rows and columns are boundary cases; interior cells\n'
          '\t// are initialized by RECURSE_M before the next row uses them.\n'
          '\tfor (unsigned i = 0; i < uPrefixCountA; ++i)\n'
          '\t\tmemset(TB[i], 0, i < 2 ? uPrefixCountB : 2);\n'
          '#else\n' + clear_grid + '\n#endif')
    path = root / 'libMems/libMems/HomologyHMM/homologymain.cc'
    patch(path, '  prediction.resize(iPathLength);',
          '#ifdef MAUVE_PROFILE_ROWS\n'
          '  const int homologous = HomologyDPTable::getId("homologous");\n'
          '#endif\n  prediction.resize(iPathLength);')
    posterior = '    double iPosterior = pFWDP->getProb("homologous",i+1)*pBWDP->getProb("homologous",i+1)/iFWProb;'
    patch(path, posterior, '#ifdef MAUVE_PROFILE_ROWS\n'
          '    double iPosterior = pFWDP->getProb(homologous,i+1)*pBWDP->getProb(homologous,i+1)/iFWProb;\n'
          '#else\n' + posterior + '\n#endif')
    path = root / 'libMems/libMems/SortedMerList.cpp'
    patch(path, '#include "libMems/SortedMerList.h"',
          '#include "libMems/SortedMerList.h"\n#include "mauve_seed.h"')
    start = 'uint64 SortedMerList::GetSeedMer( gnSeqI offset ) const\n{\n'
    patch(path, start, start + '''#ifdef MAUVE_SEED_LOOKUP
    static_assert(OPT_HEADER_ALPHABET_BITS == 2, "Seed lookup requires two-bit DNA");
    if (header.seed_length > 0 && header.seed_length <= 32 &&
        header.seed_weight > 0 && header.seed_weight <= 32)
        return PackSeedMer(SortedMerList::GetMer(offset), header.seed, header.seed_length, header.seed_weight);
#endif
''')
    path = root / 'libMems/libMems/CompactGappedAlignment.h'
    patch(path, '\tcga.SetLeftEnd(cga_seq,left_bit+1);\n',
          '\tcga.SetLeftEnd(cga_seq,left_bit+1);\n'
          '#ifdef MAUVE_FAST_TRANSLATE\n'
          '\t// A gapless source span only shifts the origin. The destination\n'
          '\t// bitmaps, lengths, and rank indexes are already the final result.\n'
          '\tif( right_bit - left_bit == cga.Length(cga_seq) )\n'
          '\t\treturn;\n'
          '#endif\n')
    patch(path, '#include <algorithm>', '#include <algorithm>\n#include <boost/function_output_iterator.hpp>')
    scalar_index = ('\t\tfor( size_t indie = 0; indie + INDEX_INTERVAL <= bvec.size(); indie += INDEX_INTERVAL )\n'
                    '\t\t{\n\t\t\tsize_t end = indie + INDEX_INTERVAL;\n\t\t\tsize_t ct = 0;\n'
                    '\t\t\tfor( size_t i = indie; i < end; ++i )\n\t\t\t\tct += bvec.test(i);\n'
                    '\t\t\tbcount[seqI].push_back( ct + bcount[seqI].back() );\n\t\t}')
    block_index = '''#ifdef MAUVE_FAST_TRANSLATE
        static_assert(INDEX_INTERVAL % bitset_t::bits_per_block == 0, "Index must contain whole blocks");
        const size_t blocks_per_index = INDEX_INTERVAL / bitset_t::bits_per_block;
        const size_t complete_blocks = (bvec.size() / INDEX_INTERVAL) * blocks_per_index;
        size_t block_index = 0, count = 0;
        bcount[seqI].reserve(bvec.size() / INDEX_INTERVAL + 1);
        boost::to_block_range(bvec, boost::make_function_output_iterator([&](bitset_t::block_type block) {
            if (block_index >= complete_blocks) return;
            count += __builtin_popcountll(block);
            if (++block_index % blocks_per_index == 0) bcount[seqI].push_back(count);
        }));
#else
''' + scalar_index + '\n#endif'
    patch(path, scalar_index, block_index)
    path = root / 'libMems/libMems/Interval.h'
    interval_start = ('void GenericInterval<GappedBaseImpl>::GetAlignment( std::vector< bitset_t >& align_matrix ) const\n{\n')
    patch(path, interval_start, interval_start + '''#ifdef MAUVE_FAST_TRANSLATE
    // A single complete child already has the required bitmap representation.
    // Check the residue counts because the general path deliberately truncates
    // each row to Length(seqI), even if a child has surplus set bits.
    if (matches.size() == 1 && matches[0]->SeqCount() == this->SeqCount() &&
        matches[0]->AlignmentLength() == this->AlignmentLength()) {
        matches[0]->GetAlignment(align_matrix);
        bool complete = align_matrix.size() == this->SeqCount();
        for (uint seqI = 0; complete && seqI < this->SeqCount(); ++seqI) {
            if (matches[0]->LeftEnd(seqI) == NO_MATCH || matches[0]->Length(seqI) == 0) {
                align_matrix[seqI].resize(this->AlignmentLength());
                align_matrix[seqI].reset();
            } else if (align_matrix[seqI].size() != this->AlignmentLength() ||
                       align_matrix[seqI].count() != matches[0]->Length(seqI)) {
                complete = false;
            }
        }
        if (complete) return;
    }
#endif
''')
    def sources(folder, key):
        text = (folder / 'Makefile.am').read_text().replace('\\\n', ' ')
        return [folder / f for f in re.search(r'^' + key + r'\s*=([^\n]+)', text, re.M)[1].split()]
    files = sources(root / 'libGenome/libGenome', 'LIBGENOME_SRC') + sources(root / 'muscle/libMUSCLE', 'LIBMUSCLE_SRC')
    for key in ['LIBMEMS_SRC', 'HOMOLOGYHMM_SRC', 'DMSML_SRC']:
        files += sources(root / 'libMems/libMems', key)
    files += [root / 'mauveAligner/src' / f for f in ['progressiveMauve.cpp', 'UniqueMatchFinder.cpp']]
    files += list((boost / 'libs/filesystem/src').glob('*.cpp')) + [boost / 'libs/system/src/error_code.cpp', boost / 'libs/iostreams/src/mapped_file.cpp']
    files += [HERE / 'optimizations/profile_row.cpp']
    files += [HERE / 'optimizations/seed_lookup.cpp']
    flags = ['-O3', '-msimd128', '-DNDEBUG', '-D_LIB', '-DUSE_LIBC', '-DBOOST_NO_CXX11_SCOPED_ENUMS',
             '-Wno-deprecated-declarations', '-Wno-register', '-Wno-inconsistent-missing-override', '-Wno-c++11-narrowing']
    flags += ['-I' + str(root / f) for f in ['libGenome', 'muscle', 'libMems', 'boost_1_65_1']]
    flags += ['-I' + str(HERE / 'optimizations')]
    if not baseline:
        flags += ['-flto', '-DMAUVE_PROFILE_ROWS', '-DMAUVE_FAST_TRANSLATE', '-DMAUVE_SEED_LOOKUP', '-DMAUVE_COMPACT_TRACE', '-DMAUVE_LAZY_TRACE', '-DMAUVE_ROW_GAPS', '-DMAUVE_LOCAL_D_SCORE']
    exceptions = ['-fexceptions'] if baseline else ['-fwasm-exceptions']
    obj = root / ('objects-baseline' if baseline else 'objects-optimized'); obj.mkdir(exist_ok=True)
    def compile_one(file):
        relative = file.relative_to(root) if file.is_relative_to(root) else file.relative_to(HERE)
        dest = obj / (str(relative).replace('/', '_') + '.o')
        compiler = 'emcc' if file.suffix == '.c' else 'em++'
        extra = ['-Wno-error=implicit-function-declaration'] if file.suffix == '.c' else ['-std=c++14', *exceptions]
        # Always compile: changes to dependency headers must invalidate objects too.
        subprocess.run([compiler, *flags, *extra, '-c', str(file), '-o', str(dest)], check=True)
        return dest
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        objects = list(pool.map(compile_one, files))
    output.mkdir(parents=True, exist_ok=True)
    link_flags = ['-sDISABLE_EXCEPTION_CATCHING=0'] if baseline else ['-flto']
    if profiling:
        link_flags += ['--profiling-funcs']
    subprocess.run(['em++', *map(str, objects), '-O3', '-msimd128', *exceptions, *link_flags,
                    '-sALLOW_MEMORY_GROWTH=1', '-sMAXIMUM_MEMORY=2147483648', '-sSTACK_SIZE=8388608',
                    '-sMODULARIZE=1', '-sEXPORT_ES6=1', '-sINVOKE_RUN=0', "-sEXPORTED_RUNTIME_METHODS=['FS','callMain']",
                    '-sFORCE_FILESYSTEM=1', '-sENVIRONMENT=web,worker,node', '-o', str(output / 'progressiveMauve.mjs')], check=True)
    for name in PINS:
        shutil.copyfile(root / name / 'COPYING', output / (name + '-COPYING'))
    shutil.copyfile(root / 'libMems/LICENSE', output / 'libMems-LICENSE')
    shutil.copyfile(boost / 'LICENSE_1_0.txt', output / 'Boost-LICENSE')
    local_sources = [HERE / 'build.py', *sorted((HERE / 'optimizations').glob('*'))]
    manifest = {'compiler': 'Emscripten 4.0.15',
                'configuration': {'local_deletion_score': not baseline, 'row_gap_loads': not baseline, 'lazy_traceback': not baseline, 'compact_traceback': not baseline, 'seed_lookup': not baseline,
                                  'packed_profiles': not baseline, 'hoisted_homology_state': not baseline,
                                  'lto': not baseline, 'profile_rows': not baseline, 'fast_translate': not baseline,
                                  'exceptions': 'javascript' if baseline else 'wasm', 'profiling': profiling},
                'local_sources': {str(p.relative_to(HERE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in local_sources},
                'sources': {name: {'url': 'https://github.com/koadman/' + name, 'revision': rev} for name, rev in PINS.items()},
                'boost': {'url': 'https://archives.boost.io/release/1.65.1/source/boost_1_65_1.tar.bz2', 'sha256': BOOST_SHA256},
                'wasm_sha256': hashlib.sha256((output / 'progressiveMauve.wasm').read_bytes()).hexdigest(),
                'rebuild': 'python3 build.py --work /tmp/mauve-wasm-build --output ./rebuilt' + (' --baseline' if baseline else '') + (' --profiling' if profiling else '')}
    (output / 'SOURCES.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=HERE.parent / 'mauve_web/static/wasm')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--baseline', action='store_true', help='Original scalar scoring, no LTO, JavaScript exception handling')
    parser.add_argument('--profiling', action='store_true', help='Preserve C++ function names in optimized output')
    args = parser.parse_args()
    build(args.work.resolve(), args.output.resolve(), args.jobs, args.baseline, args.profiling)
