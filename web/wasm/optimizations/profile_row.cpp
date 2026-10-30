#include "libMUSCLE/muscle.h"
#include "mauve_profile_row.h"
#include <wasm_simd128.h>

namespace muscle {
PackedProfileRows::PackedProfileRows(const ProfPos *b, unsigned count, bool pack) : b(b), count(count) {
    if (!pack || g_PPScore.get() != PPSCORE_SPN || count < 8) return;
    packed.resize(size_t(count) * 4);
    for (unsigned letter = 0; letter < 4; ++letter)
        for (unsigned j = 0; j < count; ++j)
            packed[size_t(letter) * count + j] = b[j].m_AAScores[letter];
}

void PackedProfileRows::score(const ProfPos &a, SCORE *scores) const {
    if (packed.empty() || g_PPScore.get() != PPSCORE_SPN) {
        ScoreProfPos2Row(a, b, count, scores); return;
    }
    unsigned used = 0;
    const SCORE *columns[4];
    FCOUNT weights[4];
    v128_t vectorWeights[4];
    for (; used < 4; ++used) {
        const unsigned letter = a.m_uSortOrder[used];
        const FCOUNT weight = a.m_fcCounts[letter];
        if (weight == 0) break;
        if (letter >= 4) { ScoreProfPos2Row(a, b, count, scores); return; }
        columns[used] = packed.data() + size_t(letter) * count;
        weights[used] = weight;
        vectorWeights[used] = wasm_f32x4_splat(weight);
    }
    const SCORE center = g_scoreCenter.get();
    const v128_t vectorCenter = wasm_f32x4_splat(center);
    unsigned j = 0;
    for (; j + 4 <= count; j += 4) {
        v128_t sum = wasm_f32x4_splat(0);
        for (unsigned n = 0; n < used; ++n)
            sum = wasm_f32x4_add(sum, wasm_f32x4_mul(vectorWeights[n], wasm_v128_load(columns[n] + j)));
        wasm_v128_store(scores + j, wasm_f32x4_sub(sum, vectorCenter));
    }
    for (; j < count; ++j) {
        SCORE sum = 0;
        for (unsigned n = 0; n < used; ++n) sum += weights[n] * columns[n][j];
        scores[j] = sum - center;
    }
}

// Score one DP row with invariant scoring mode and sparse profile weights.
// Keep the scalar summation order, including the initial +0, exactly intact.
void ScoreProfPos2Row(const ProfPos &a, const ProfPos *b, unsigned count, SCORE *scores)
{
    if (g_PPScore.get() != PPSCORE_SPN) {
        for (unsigned j = 0; j < count; ++j)
            scores[j] = ScoreProfPos2(a, b[j]);
        return;
    }
    unsigned letters[4], used = 0;
    FCOUNT weights[4];
    for (; used < 4; ++used) {
        const unsigned letter = a.m_uSortOrder[used];
        const FCOUNT weight = a.m_fcCounts[letter];
        if (weight == 0) break;
        letters[used] = letter;
        weights[used] = weight;
    }
    const SCORE center = g_scoreCenter.get();
    for (unsigned j = 0; j < count; ++j) {
        SCORE score = 0;
        for (unsigned n = 0; n < used; ++n)
            score += weights[n] * b[j].m_AAScores[letters[n]];
        scores[j] = score - center;
    }
}
}
