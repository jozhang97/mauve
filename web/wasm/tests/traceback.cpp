#include "libMUSCLE/muscle.h"
#include "libMUSCLE/profile.h"
#include "libMUSCLE/pwpath.h"
#include <vector>
#include <cstring>
#include <cstdint>
#include <cstdio>

namespace muscle {
unsigned char TraceCellCandidate(unsigned, unsigned);
unsigned char TraceCellReference(unsigned, unsigned);
SCORE NWSmall(const ProfPos*, unsigned, const ProfPos*, unsigned, PWPath&);
SCORE NWSmallReference(const ProfPos*, unsigned, const ProfPos*, unsigned, PWPath&);
}

int main() {
    using namespace muscle;
    uint32_t random = 37;
    unsigned cases = 0;
    auto draw = [&]() { random = random * 1664525u + 1013904223u; return random; };
    g_PPScore.get() = PPSCORE_SPN;
    g_scoreCenter.get() = 0.5f;
    for (auto term : {TERMGAPS_Full, TERMGAPS_Half, TERMGAPS_Ext})
    for (unsigned pattern = 0; pattern < 3; ++pattern)
    for (unsigned na : {1u, 2u, 17u, 63u, 64u, 65u, 129u, 513u, 1025u})
    // Reverse column order to exercise both growth and reuse of larger caches.
    for (unsigned nb : {1025u, 513u, 129u, 65u, 64u, 63u, 17u, 2u, 1u}) {
        g_TermGaps.get() = term;
        g_scoreGapExtend.get() = pattern == 0 ? 0.0f : -0.25f;
        std::vector<ProfPos> a(na), b(nb);
        for (auto* rows : {&a, &b}) for (auto& p : *rows) {
            for (unsigned n = 0; n < 20; ++n) p.m_uSortOrder[n] = n;
            p.m_scoreGapOpen = pattern == 0 ? 0.0f : -float(draw() % 32 + 1) / 4;
            p.m_scoreGapClose = pattern == 0 ? 0.0f : -float(draw() % 32 + 1) / 4;
            for (unsigned n = 0; n < 4; ++n) {
                p.m_fcCounts[n] = pattern == 0 ? 0.25f : float(draw() % 16 + 1) / 64;
                p.m_AAScores[n] = pattern == 0 ? 0.0f : float(int(draw() % 256) - 128) / 32;
            }
        }
        auto aa = a, bb = b;
        PWPath expected, actual;
        const SCORE reference = NWSmallReference(a.data(), na, b.data(), nb, expected);
        const SCORE candidate = NWSmall(aa.data(), na, bb.data(), nb, actual);
        if (std::memcmp(&reference, &candidate, sizeof(SCORE)) || !actual.Equal(expected)) {
            fprintf(stderr, "Mismatch %u,%u pattern %u term %d\n", na, nb, pattern, term);
            return 1;
        }
        for (unsigned i = 0; i <= na; ++i) for (unsigned j = 0; j <= nb; ++j) {
            if (TraceCellCandidate(i, j) != TraceCellReference(i, j)) {
                fprintf(stderr, "Trace cell mismatch %u,%u at %u,%u\n", na, nb, i, j);
                return 2;
            }
        }
        ++cases;
    }
    printf("Traceback cells, paths, and scores match across %u varying cache shapes and gap cases.\n", cases);
}
