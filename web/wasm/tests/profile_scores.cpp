// Differential test against MUSCLE's original scalar scorer in scorepp.cpp.
#include "libMUSCLE/muscle.h"
#include "libMUSCLE/profile.h"
#include "mauve_profile_row.h"
#include <cstdint>

namespace muscle {
TLS<PPSCORE> g_PPScore;
TLS<SCORE> g_scoreCenter;
void Quit(const char[], ...) { abort(); }
}

int main() {
    using namespace muscle;
    uint32_t state = 37;
    auto random = [&]() -> uint32_t { return state = state * 1664525u + 1013904223u; };
    const PPSCORE modes[] = {PPSCORE_SPN, PPSCORE_SP, PPSCORE_LE, PPSCORE_SV};
    for (PPSCORE mode : modes) {
        g_PPScore.get() = mode;
        for (unsigned trial = 0; trial < 2000; ++trial) {
            ProfPos a = {}, b[33] = {};
            for (unsigned n = 0; n < 20; ++n) a.m_uSortOrder[n] = n;
            // Permute the four nucleotide letters; vary the early zero cutoff.
            for (unsigned n = 3; n > 0; --n) {
                unsigned j = random() % (n + 1), tmp = a.m_uSortOrder[n];
                a.m_uSortOrder[n] = a.m_uSortOrder[j]; a.m_uSortOrder[j] = tmp;
            }
            // Exercise the fallback for SPN inputs with non-nucleotide letters.
            if (trial % 7 == 0) a.m_uSortOrder[0] = 19;
            for (unsigned n = 0; n < trial % 5; ++n)
                a.m_fcCounts[a.m_uSortOrder[n]] = (random() % 1024 + 1) / 1024.0f;
            a.m_fOcc = (random() % 1024) / 1024.0f;
            g_scoreCenter.get() = (int(random() % 4096) - 2048) / 1024.0f;
            for (auto &p : b) {
                p.m_fOcc = (random() % 1024) / 1024.0f;
                for (auto &score : p.m_AAScores)
                    score = mode == PPSCORE_LE ? (random() % 4096 + 1) / 1024.0f
                                              : (int(random() % 8192) - 4096) / 1024.0f;
            }
            SCORE scores[34];
            for (auto &s : scores) s = 123456.0f;
            unsigned count = trial % 34; // zero, singleton, and vector tails
            PackedProfileRows(b, count).score(a, scores);
            SCORE unpacked[34];
            for (auto &s : unpacked) s = 123456.0f;
            PackedProfileRows(b, count, false).score(a, unpacked);
            if (scores[count] != 123456.0f) return 2;
            if (unpacked[count] != 123456.0f) return 3;
            for (unsigned j = 0; j < count; ++j) {
                SCORE expected = ScoreProfPos2(a, b[j]);
                if (memcmp(&expected, &scores[j], sizeof(SCORE)) ||
                    memcmp(&expected, &unpacked[j], sizeof(SCORE))) {
                    fprintf(stderr, "Score mismatch: mode=%d trial=%u column=%u\n", mode, trial, j);
                    return 1;
                }
            }
        }
    }
    puts("Profile row scores match scalar scores bit for bit (8,000 cases).");
}
