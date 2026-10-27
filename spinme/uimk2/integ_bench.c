/* Time one scripted Core B sequence. N=100, sample stdev (n-1), same
 * clock helpers as bench_ui (bench_time.h). No ASan: see integ-bench
 * in the Makefile (BENCH_CFLAGS, -O2).
 *
 * Run from spinme/uimk2:
 *   make integ-bench
 * Stdout and build/integ_bench.txt both get the row.
 */
#include "bench_time.h"
#include "integ_script.h"

#include <stdarg.h>
#include <stdio.h>

#define BENCH_N 100
#define BENCH_WARMUP 8

static volatile uint32_t bench_sink;
static FILE *report;

static void emit(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    if (report != NULL) {
        va_start(ap, fmt);
        vfprintf(report, fmt, ap);
        va_end(ap);
    }
}

int main(void) {
    double samples[BENCH_N];
    bench_stats st;
    int i;
    int checks = 0;
    int failures;

    clock_init();
    report = fopen("build/integ_bench.txt", "w");
    if (report == NULL) {
        fprintf(stderr, "integ_bench: could not write build/integ_bench.txt\n");
    }
    emit("uimk2 host integration bench\n");
    emit("N=%d warmup=%d discarded stdev=sample(n-1) clock=%s "
         "cflags=-O2 sanitize=off\n",
         BENCH_N, BENCH_WARMUP, clock_name());
    emit("sequence=screen_on,volume,poll,press,miss,scroll,screen_off\n");
    emit("mean_us is us per full virtual-clock script. Overflow checks "
         "stay on the ASan test_integ binary.\n");
    emit("%-22s %-20s %5s %10s %10s %10s %10s\n", "scenario", "op", "n",
         "mean_us", "stdev_us", "min_us", "max_us");
    emit("%-22s %-20s %5s %10s %10s %10s %10s\n", "----------------------",
         "--------------------", "-----", "----------", "----------",
         "----------", "----------");

    for (i = 0; i < BENCH_WARMUP; i++) {
        failures = integ_sequence_run(&checks);
        bench_sink += (uint32_t)checks;
        if (failures != 0) {
            fprintf(stderr, "integ_bench: warmup failed (%d)\n", failures);
            if (report != NULL) {
                fclose(report);
            }
            return 1;
        }
    }
    for (i = 0; i < BENCH_N; i++) {
        uint64_t t0;
        uint64_t t1;
        t0 = mono_ticks();
        failures = integ_sequence_run(&checks);
        t1 = mono_ticks();
        bench_sink += (uint32_t)checks;
        if (failures != 0) {
            fprintf(stderr, "integ_bench: sample %d failed (%d)\n", i,
                    failures);
            if (report != NULL) {
                fclose(report);
            }
            return 1;
        }
        samples[i] = ticks_to_us(t1 - t0);
    }
    stats_of(samples, BENCH_N, &st);
    emit("%-22s %-20s %5d %10.2f %10.2f %10.2f %10.2f\n", "scripted_core_b",
         "full_sequence", BENCH_N, st.mean_us, st.stdev_us, st.min_us,
         st.max_us);
    emit("sink=%u\n", (unsigned)bench_sink);
    if (report != NULL) {
        emit("report=build/integ_bench.txt\n");
        fclose(report);
        report = NULL;
    }
    return 0;
}
