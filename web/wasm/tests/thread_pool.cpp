// Scheduler contract: exact coverage, bounded nesting, exception propagation,
// and restoration of TLS identity on the caller after joins.
#include "thread_pool.h"
#include <cassert>
#include <stdexcept>
int main() {
    setenv("MAUVE_THREADS", "4", 1);
    std::atomic<unsigned> visits[37]{};
    mauve_parallel_for(0, [&](size_t) { assert(false); });
    mauve_parallel_for(37, [&](size_t i) {
        assert(mauve_thread_index < 4);
        const auto index = mauve_thread_index;
        mauve_parallel_for(11, [&](size_t) {
            assert(mauve_thread_index == index);
            visits[i].fetch_add(1);
        });
    });
    for (auto& n : visits) assert(n == 11);
    assert(mauve_thread_index == 0 && !mauve_in_parallel);
    bool caught = false;
    try {
        mauve_parallel_for(37, [&](size_t i) { if (i == 7) throw std::runtime_error("expected"); });
    } catch (const std::runtime_error&) { caught = true; }
    assert(caught && mauve_thread_index == 0 && !mauve_in_parallel);
    unsigned serial = 0;
    mauve_parallel_pairs(1, 4, [&](size_t) { assert(false); });
    mauve_parallel_for(1, [&](size_t i) { assert(i == 0); ++serial; });
    assert(serial == 1);
}
