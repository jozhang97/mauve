#ifndef MAUVE_THREAD_POOL_H
#define MAUVE_THREAD_POOL_H
#include <algorithm>
#include <atomic>
#include <cstdlib>
#include <exception>
#include <mutex>
#include <thread>
#include <vector>
extern thread_local unsigned mauve_thread_index;
extern thread_local bool mauve_in_parallel;
inline unsigned mauve_thread_count() {
    // The JS caller validates this value and preallocates the worker pool.
    const char* value = std::getenv("MAUVE_THREADS");
    return value ? unsigned(std::max(1, std::min(16, std::atoi(value)))) : 1;
}
inline std::mutex& mauve_sequence_mutex() {
    static std::mutex mutex;
    return mutex;
}
template<class Fn> void mauve_parallel_pairs(size_t count, unsigned team, Fn fn, size_t begin = 1) {
    if (count <= begin) return;
    team = std::min(team, unsigned(count - begin));
    if (team <= 1 || mauve_in_parallel) {
        for (size_t i = begin; i < count; ++i) fn(i);
        return;
    }
    std::atomic<size_t> next(begin);
    std::exception_ptr failure;
    std::mutex failure_mutex;
    auto work = [&](unsigned index) {
        const unsigned previous_index = mauve_thread_index;
        mauve_thread_index = index;
        mauve_in_parallel = true;
        try {
            for (;;) {
                size_t i = next.fetch_add(1, std::memory_order_relaxed);
                if (i >= count) break;
                fn(i);
            }
        } catch (...) {
            next.store(count, std::memory_order_relaxed);
            std::lock_guard<std::mutex> lock(failure_mutex);
            if (!failure) failure = std::current_exception();
        }
        mauve_in_parallel = false;
        mauve_thread_index = previous_index;
    };
    std::vector<std::thread> threads;
    try {
        for (unsigned i = 1; i < team; ++i) threads.emplace_back(work, i);
    } catch (...) {
        next.store(count, std::memory_order_relaxed);
        for (auto& thread : threads) thread.join();
        throw;
    }
    work(0);
    for (auto& thread : threads) thread.join();
    if (failure) std::rethrow_exception(failure);
}
template<class Fn> void mauve_parallel_for(size_t count, Fn fn) {
    mauve_parallel_pairs(count, mauve_thread_count(), fn, 0);
}
#endif
