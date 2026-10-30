#include "libMems/HomologyHMM/parameters.h"
#include <cstring>
#include <cstdint>

int main() {
    uint32_t seed = 37;
    unsigned cases = 0;
    for (double gc : {0.2, 0.5, 0.8})
    for (unsigned length : {1u, 2u, 17u, 511u, 1024u})
    for (unsigned pattern = 0; pattern < 5; ++pattern) {
        Params params = getAdaptedHoxdMatrixParameters(gc);
        std::string sequence(length, '1');
        for (unsigned i = 0; i < length; ++i) {
            seed = seed * 1664525u + 1013904223u;
            if (pattern == 1) sequence[i] = '3' + (seed >> 30);
            if (pattern == 2) sequence[i] = i % 10 ? '8' : '7';
            if (pattern == 3) sequence[i] = '1' + (seed >> 29);
            if (pattern == 4) sequence[i] = i < length / 2 ? '1' : '6';
        }
        HomologyDPTable *forward, *backward;
        HomologyBaumWelch bw;
        const bfloat probability = Forward(&forward, params, &sequence[0], length);
        Backward(bw, forward, &backward, params, &sequence[0], length);
        const int state = HomologyDPTable::getId("homologous");
        std::string expected;
        for (unsigned i = 0; i < length; ++i) {
            const double original = forward->getProb("homologous", i + 1) * backward->getProb("homologous", i + 1) / probability;
            const double candidate = forward->getProb(state, i + 1) * backward->getProb(state, i + 1) / probability;
            if (std::memcmp(&original, &candidate, sizeof(double))) return 1;
            expected += original >= 0.9 ? 'H' : 'N';
        }
        delete forward; delete backward;
        std::string prediction;
        run(sequence, prediction, params);
        if (prediction != expected) return 2;
        ++cases;
    }
    std::cout << "Homology posteriors match bit for bit and predictions match (" << cases << " cases).\n";
}
