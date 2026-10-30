#include "mauve_seed.h"
#include <array>
#include <utility>

namespace mems {
namespace {
// Pack the selected bases from one byte (four two-bit DNA symbols).
// Store the number of output bits alongside the packed byte in one lookup.
constexpr std::uint16_t entry(unsigned key) {
    unsigned mask = key >> 8, value = key & 255, packed = 0, bits = 0;
    for (int shift = 6; shift >= 0; shift -= 2) {
        if (mask & 8) { packed = (packed << 2) | ((value >> shift) & 3); bits += 2; }
        mask <<= 1;
    }
    return std::uint16_t((bits << 8) | packed);
}
template<std::size_t... I>
constexpr std::array<std::uint16_t, sizeof...(I)> table(std::index_sequence<I...>) {
    return {{entry(I)...}};
}
constexpr auto lookup = table(std::make_index_sequence<4096>{});
}

std::uint64_t PackSeedMer(std::uint64_t mer, std::uint64_t seed, unsigned length, unsigned weight) {
    std::uint32_t pattern = std::uint32_t(seed) << (32 - length);
    std::uint64_t result = 0;
    while (pattern) {
        const auto packed = lookup[((pattern >> 28) << 8) | unsigned(mer >> 56)];
        result = (result << (packed >> 8)) | (packed & 255);
        pattern <<= 4;
        mer <<= 8;
    }
    return result << (64 - 2 * weight);
}
}
