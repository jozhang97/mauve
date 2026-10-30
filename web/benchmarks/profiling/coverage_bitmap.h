#pragma once
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <vector>
// Experimental coverage-only bitmap. resize initializes an empty bitmap;
// unlike dynamic_bitset it intentionally does not preserve previous contents.
class MauveCoverageBitmap {
    std::vector<uint64_t> words;
    size_t length = 0;
public:
    void resize(size_t n, bool value = false) {
        assert(!value);
        length = n;
        words.assign((n + 63) / 64, 0);
    }
    size_t size() const { return length; }
    void set(size_t pos, bool value = true) {
        assert(pos < length);
        const uint64_t mask = uint64_t(1) << (pos % 64);
        if (value) words[pos / 64] |= mask;
        else words[pos / 64] &= ~mask;
    }
    void set_range(size_t first, size_t count) {
        assert(first <= length && count <= length - first);
        if (!count) return;
        const size_t last = first + count - 1;
        const uint64_t left = ~uint64_t(0) << (first % 64);
        const uint64_t right = ~uint64_t(0) >> (63 - last % 64);
        if (first / 64 == last / 64) words[first / 64] |= left & right;
        else {
            words[first / 64] |= left;
            std::fill(words.begin() + first / 64 + 1, words.begin() + last / 64, ~uint64_t(0));
            words[last / 64] |= right;
        }
    }
    size_t count() const {
        size_t result = 0;
        for (uint64_t word : words) result += __builtin_popcountll(word);
        return result;
    }
};
