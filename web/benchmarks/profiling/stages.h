#pragma once
#include <atomic>
#include <chrono>
#include <cstdio>
namespace mauve_profile {
struct Counter { std::atomic<long long> ns{0}, calls{0}; };
inline Counter* counters() { static Counter values[20]; return values; }
struct Scope {
  int id;
  std::chrono::steady_clock::time_point start;
  explicit Scope(int i): id(i), start(std::chrono::steady_clock::now()) {}
  ~Scope() {
    auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();
    counters()[id].ns.fetch_add(elapsed, std::memory_order_relaxed);
    counters()[id].calls.fetch_add(1, std::memory_order_relaxed);
  }
};
struct Report {
  ~Report() {
    const char* names[] = {"engine", "backbone", "progressive", "guide_distance", "alignment_tree", "profile_alignment", "gapped_alignment", "recursive_pairs", "pairwise_hss", "muscle_refine", "muscle_profile", "muscle_align", "muscle_refine_fast", "muscle_profile_fast", "single_copy_distance", "seed_occurrence", "nw_small", "muscle_tree", "refine_windows", "refine_horizontal"};
    for (int i=0; i<20; ++i)
      std::fprintf(stderr, "MAUVE_STAGE %s %.6f %lld\n", names[i], counters()[i].ns.load()/1e6, counters()[i].calls.load());
  }
};
}
