/* Monotonic clock and sample standard deviation for uimk2 benches.
 *
 * Apple uses mach_absolute_time. Other hosts use CLOCK_MONOTONIC.
 * stdev_us uses the sample divisor n-1. bench_ui.c and integ_bench.c
 * both include this header. The ASan test binaries do not.
 */
#ifndef BENCH_TIME_H
#define BENCH_TIME_H

#if !defined(__APPLE__) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 199309L
#endif

#include <math.h>
#include <stdint.h>

#if defined(__APPLE__)
#include <mach/mach_time.h>
#else
#include <time.h>
#endif

typedef struct {
    double mean_us;
    double stdev_us;
    double min_us;
    double max_us;
} bench_stats;

#if defined(__APPLE__)
static double bench_ns_per_tick;

static inline void clock_init(void) {
    mach_timebase_info_data_t tb;
    mach_timebase_info(&tb);
    bench_ns_per_tick = (double)tb.numer / (double)tb.denom;
}

static inline const char *clock_name(void) {
    return "mach_absolute_time";
}

static inline uint64_t mono_ticks(void) {
    return mach_absolute_time();
}

static inline double ticks_to_us(uint64_t dt) {
    return (double)dt * bench_ns_per_tick / 1000.0;
}
#else
static inline void clock_init(void) {}

static inline const char *clock_name(void) {
    return "CLOCK_MONOTONIC";
}

static inline uint64_t mono_ticks(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static inline double ticks_to_us(uint64_t dt) {
    return (double)dt / 1000.0;
}
#endif

/* Sample standard deviation: divisor is n-1. n must be at least 2. */
static inline void stats_of(const double *us, int n, bench_stats *s) {
    int i;
    double sum = 0.0;
    double acc = 0.0;
    s->min_us = us[0];
    s->max_us = us[0];
    for (i = 0; i < n; i++) {
        sum += us[i];
        if (us[i] < s->min_us) {
            s->min_us = us[i];
        }
        if (us[i] > s->max_us) {
            s->max_us = us[i];
        }
    }
    s->mean_us = sum / (double)n;
    for (i = 0; i < n; i++) {
        double diff = us[i] - s->mean_us;
        acc += diff * diff;
    }
    s->stdev_us = sqrt(acc / (double)(n - 1));
}

#endif /* BENCH_TIME_H */
