#include <omp.h>
#include <cstdio>
#include <cstdlib>
#include <cerrno>
#include <algorithm>
__thread unsigned mauve_thread_index = 0;
extern int mauve_main(int, char **);
int main(int argc, char **argv) {
    // Upstream TLS arrays have 16 slots. Nested teams would alias those slots.
    // Let idle workers sleep while the serial alignment stages run.
    setenv("OMP_WAIT_POLICY", "PASSIVE", 0);
    int threads = std::min(8, omp_get_num_procs());
    if (const char *value = std::getenv("MAUVE_THREADS")) {
        char *end = nullptr;
        errno = 0;
        long n = std::strtol(value, &end, 10);
        if (errno || end == value || *end || n < 1 || n > 16) {
            std::fprintf(stderr, "MAUVE_THREADS must be an integer from 1 to 16\n");
            return 2;
        }
        threads = static_cast<int>(n);
    }
    omp_set_dynamic(0);
    omp_set_max_active_levels(1);
    omp_set_num_threads(threads);
    std::fprintf(stderr, "Mauve ARM64: up to %d OpenMP threads\n", threads);
    return mauve_main(argc, argv);
}
