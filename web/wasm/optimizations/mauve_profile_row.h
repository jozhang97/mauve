#ifndef MAUVE_PROFILE_ROW_H
#define MAUVE_PROFILE_ROW_H
#include "libMUSCLE/profile.h"
#include <vector>

namespace muscle {
void ScoreProfPos2Row(const ProfPos &a, const ProfPos *b, unsigned count, SCORE *scores);
class PackedProfileRows {
    const ProfPos *b;
    unsigned count;
    std::vector<SCORE> packed;
public:
    PackedProfileRows(const ProfPos *b, unsigned count, bool pack = true);
    void score(const ProfPos &a, SCORE *scores) const;
};
}
#endif
