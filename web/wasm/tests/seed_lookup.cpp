#include "mauve_seed.h"
#include <cstdint>
#include <iostream>

static std::uint64_t reference(std::uint64_t mer, std::uint64_t seed, unsigned length, unsigned weight) {
    std::uint64_t result = 0;
    for (unsigned i = 0; i < length; ++i)
        if (seed & (std::uint64_t(1) << (length - i - 1)))
            result = (result << 2) | ((mer >> (62 - i * 2)) & 3);
    return result << (64 - weight * 2);
}

int main() {
    unsigned checked = 0;
    for (unsigned mask = 0; mask < 16; ++mask)
    for (unsigned value = 0; value < 256; ++value) {
        const unsigned weight = mask ? __builtin_popcount(mask) : 1;
        const std::uint64_t mer = std::uint64_t(value) << 56;
        if (mems::PackSeedMer(mer, mask, 4, weight) != reference(mer, mask, 4, weight)) return 1;
        ++checked;
    }
    std::uint32_t state = 37;
    auto random = [&]() { return state = state * 1664525u + 1013904223u; };
    for (unsigned length = 1; length <= 32; ++length)
    for (unsigned trial = 0; trial < 3000; ++trial) {
        const std::uint64_t mask = (std::uint64_t(1) << length) - 1;
        const std::uint64_t seed = trial % 3 == 0 ? mask :
            ((random() & mask) | (std::uint64_t(1) << (length - 1)));
        const unsigned weight = __builtin_popcountll(seed);
        const std::uint64_t high = random(), low = random();
        const std::uint64_t mer = (high << 32) | low;
        if (mems::PackSeedMer(mer, seed, length, weight) != reference(mer, seed, length, weight)) return 2;
        ++checked;
    }
    std::cout << "Seed extraction matches scalar selection (" << checked << " cases).\n";
}
