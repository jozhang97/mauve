#ifndef MAUVE_SEED_H
#define MAUVE_SEED_H
#include <cstdint>
namespace mems {
std::uint64_t PackSeedMer(std::uint64_t mer, std::uint64_t seed, unsigned length, unsigned weight);
}
#endif
