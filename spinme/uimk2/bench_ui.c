/* Host UI benchmarks for update_render_draw and a short host_run/step burst.
 *
 * N=100 samples per cell. A discarded global warmup runs first so the core
 * clock is steady, then each op discards BENCH_WARMUP calls. stdev_us is the
 * sample standard deviation (divisor n-1). The clock is mach_absolute_time
 * on Apple and clock_gettime(CLOCK_MONOTONIC) elsewhere. This binary is
 * built without -fsanitize; see the bench-ui Makefile target.
 *
 * Each sample restores the title scroll origin (ox) before the timed call.
 * A scrolling title uses step_x=2, so the timed update advances that phase
 * by 2. Title, transport label, and volume digits are stored on the shape.
 * The painter stamps the sealed exterior; scroll state is the origin the
 * update arm advances. "pause" is the transport label while playing, and
 * "play" while paused. desired_overlay adds a closest shape over the
 * volume box and the host burst handles a volume event. matched_poll
 * omits that shape (desired == polled) and the burst also fires player_poll.
 *
 * Run from spinme/uimk2 so the optional report lands in build/bench_ui.txt.
 */
#include "bench_time.h"
#include "uimk2_host.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#define BENCH_N 100
#define BENCH_WARMUP 8
#define GLOBAL_WARMUP 4000
#define LONG_TITLE "Long Title Scrolling Now!!"
#define BURST_NOW (UPDATE_RENDER_EVERY + 1u)

typedef struct {
    const char *name;
    const char *title;
    int scrolling;
    int16_t phase_ox;
    int playing;
    const char *transport;
    int overlay;
    int desired;
    int polled;
    int post_volume;
    int poll_due;
} bench_scene;

static uimk2_zlist z;
static uint8_t curr_mem[UIMK2_FRAME_BYTES];
static uint8_t next_mem[UIMK2_FRAME_BYTES];
static int pings;
static uint16_t title_i;
static uimk2_host host;
static uimk2_ring ring;
static volatile uint32_t bench_sink;
static FILE *report;

static const bench_scene SCENES[] = {
    {"short_title_noscroll", "Song", 0, 0, 0, "play", 0, 40, 40, 0, 0},
    {"long_title_phase_0", LONG_TITLE, 1, 0, 0, "play", 0, 40, 40, 0, 0},
    {"long_title_phase_8", LONG_TITLE, 1, 8, 0, "play", 0, 40, 40, 0, 0},
    {"long_title_phase_16", LONG_TITLE, 1, 16, 0, "play", 0, 40, 40, 0, 0},
    {"long_title_phase_24", LONG_TITLE, 1, 24, 0, "play", 0, 40, 40, 0, 0},
    {"transport_playing", "Song", 0, 0, 1, "pause", 0, 40, 40, 0, 0},
    {"transport_paused", "Song", 0, 0, 0, "play", 0, 40, 40, 0, 0},
    {"desired_overlay", "Song", 0, 0, 0, "play", 1, 70, 40, 1, 0},
    {"matched_poll", "Song", 0, 0, 0, "play", 0, 40, 40, 0, 1},
};

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

static void on_ping(void *ctx) {
    int *n = (int *)ctx;
    (*n)++;
}

static void set_text(uimk2_shape *s, const char *text) {
    size_t n = strlen(text);
    if (n >= (size_t)UIMK2_ZLIST_TEXT) {
        n = (size_t)UIMK2_ZLIST_TEXT - 1u;
    }
    memset(s->text, 0, sizeof s->text);
    memcpy(s->text, text, n);
}

static uimk2_shape_desc box(uint8_t sel, int x, int y, int w, int h, int r,
                            int g, int b, int a) {
    uimk2_shape_desc d;
    memset(&d, 0, sizeof d);
    d.update_selector = sel;
    d.x = (int16_t)x;
    d.y = (int16_t)y;
    d.w = (uint16_t)w;
    d.h = (uint16_t)h;
    d.rgba[0] = (uint8_t)r;
    d.rgba[1] = (uint8_t)g;
    d.rgba[2] = (uint8_t)b;
    d.rgba[3] = (uint8_t)a;
    return d;
}

static int build_scene(const bench_scene *sc) {
    uimk2_shape_desc d[5];
    uint16_t n = 0;
    uint16_t transport_at = 0;
    uint16_t volume_at = 0;
    char vol[16];
    char des[16];
    int tr = 40;
    int tg = 160;
    int tb = 70;

    if (sc->scrolling && strlen(sc->title) < 20u) {
        fprintf(stderr, "%s: scrolling title shorter than 20\n", sc->name);
        return 0;
    }
    snprintf(vol, sizeof vol, "%d", sc->polled);
    snprintf(des, sizeof des, "%d", sc->desired);
    memset(d, 0, sizeof d);
    if (sc->overlay) {
        d[n] = box(UIMK2_UPD_FIXED, 16, 260, 72, 36, 255, 64, 64, 200);
        n++;
    }
    if (sc->playing) {
        tr = 210;
        tg = 140;
        tb = 30;
    }
    transport_at = n;
    d[n] = box(UIMK2_UPD_FIXED, 16, 188, 100, 36, tr, tg, tb, 255);
    d[n].is_transport = true;
    d[n].accept_hit = true;
    n++;
    volume_at = n;
    d[n] = box(UIMK2_UPD_FIXED, 16, 260, 72, 36, 180, 180, 200, 255);
    n++;
    title_i = n;
    d[n] = box(sc->scrolling ? (uint8_t)UIMK2_UPD_SCROLL : (uint8_t)UIMK2_UPD_FIXED,
               16, 36, 300, 28, 230, 230, 230, 255);
    d[n].step_x = sc->scrolling ? (int16_t)2 : (int16_t)0;
    n++;
    d[n] = box(UIMK2_UPD_FIXED, 0, 0, (int)PANEL_W, (int)PANEL_H, 18, 18, 22, 255);
    d[n].is_base = true;
    n++;

    uimk2_ring_init(&ring);
    pings = 0;
    if (!uimk2_zlist_build(&z, d, n, curr_mem, next_mem, &ring, on_ping,
                           &pings)) {
        fprintf(stderr, "%s: zlist build failed\n", sc->name);
        return 0;
    }
    if (sc->overlay) {
        set_text(&z.shape[0], des);
    }
    set_text(&z.shape[transport_at], sc->transport);
    set_text(&z.shape[volume_at], vol);
    set_text(&z.shape[title_i], sc->title);
    return 1;
}

static void reset_frame(const bench_scene *sc) {
    z.curr = curr_mem;
    z.next = next_mem;
    memset(curr_mem, 0, sizeof curr_mem);
    memset(next_mem, 0, sizeof next_mem);
    uimk2_ring_init(&ring);
    z.busy = false;
    z.redraw_attempt = 0;
    z.redraw_held = false;
    z.hold_redraw = false;
    z.shape[title_i].ox = sc->phase_ox;
    z.shape[title_i].oy = 0;
}

static void prep_host(const bench_scene *sc) {
    uimk2_ring_init(&ring);
    uimk2_host_init(&host, &ring, 0);
    uimk2_host_bind(&host, &z);
    host.backlight = true;
    host.playing = sc->playing ? true : false;
    host.desired = sc->desired;
    if (sc->poll_due) {
        host.poll_enabled = true;
        host.perm[UIMK2_HOST_PERM_POLL].every = 1u;
        host.perm[UIMK2_HOST_PERM_POLL].last_run = 0u;
    }
    if (sc->post_volume) {
        (void)uimk2_post_volume(&ring, sc->desired);
    }
}

static void print_row(const char *scenario, const char *op, const bench_stats *s) {
    emit("%-22s %-20s %5d %10.2f %10.2f %10.2f %10.2f\n", scenario, op, BENCH_N,
         s->mean_us, s->stdev_us, s->min_us, s->max_us);
}

static void warmup_urd(const bench_scene *sc) {
    int i;
    for (i = 0; i < BENCH_WARMUP; i++) {
        reset_frame(sc);
        uimk2_zlist_update_render_draw(&z);
        bench_sink += z.row_dirty[0];
    }
}

static void warmup_host(const bench_scene *sc) {
    int i;
    for (i = 0; i < BENCH_WARMUP; i++) {
        reset_frame(sc);
        prep_host(sc);
        (void)uimk2_host_run(&host, BURST_NOW);
        while (uimk2_host_step(&host, BURST_NOW)) {
            continue;
        }
        bench_sink += host.renders;
    }
}

/* Full-frame paints before any sample, so the first row is not still
 * climbing onto the core's steady clock. Discarded. */
static int global_warmup(void) {
    int i;
    const bench_scene *sc = &SCENES[1];
    if (!build_scene(sc)) {
        return 0;
    }
    for (i = 0; i < GLOBAL_WARMUP; i++) {
        reset_frame(sc);
        uimk2_zlist_update_render_draw(&z);
    }
    for (i = 0; i < 200; i++) {
        reset_frame(sc);
        prep_host(sc);
        (void)uimk2_host_run(&host, BURST_NOW);
        while (uimk2_host_step(&host, BURST_NOW)) {
            continue;
        }
    }
    bench_sink += z.row_dirty[0];
    bench_sink += host.renders;
    return 1;
}

static int run_scenario(const bench_scene *sc) {
    double urd[BENCH_N];
    double burst[BENCH_N];
    bench_stats st;
    int i;

    if (!build_scene(sc)) {
        return 0;
    }
    warmup_urd(sc);
    for (i = 0; i < BENCH_N; i++) {
        uint64_t t0;
        uint64_t t1;
        reset_frame(sc);
        t0 = mono_ticks();
        uimk2_zlist_update_render_draw(&z);
        t1 = mono_ticks();
        urd[i] = ticks_to_us(t1 - t0);
        bench_sink += z.row_dirty[0];
        bench_sink += (uint32_t)(uint16_t)z.shape[title_i].ox;
    }
    warmup_host(sc);
    for (i = 0; i < BENCH_N; i++) {
        uint64_t t0;
        uint64_t t1;
        reset_frame(sc);
        prep_host(sc);
        t0 = mono_ticks();
        (void)uimk2_host_run(&host, BURST_NOW);
        while (uimk2_host_step(&host, BURST_NOW)) {
            continue;
        }
        t1 = mono_ticks();
        burst[i] = ticks_to_us(t1 - t0);
        bench_sink += host.renders;
    }
    stats_of(urd, BENCH_N, &st);
    print_row(sc->name, "update_render_draw", &st);
    stats_of(burst, BENCH_N, &st);
    print_row(sc->name, "host_run_step", &st);
    return 1;
}

int main(void) {
    int i;
    int nscene = (int)(sizeof SCENES / sizeof SCENES[0]);

    clock_init();
    if (strlen(LONG_TITLE) < 20u) {
        fprintf(stderr, "long title must be at least 20 characters\n");
        return 1;
    }
    report = fopen("build/bench_ui.txt", "w");
    if (report == NULL) {
        fprintf(stderr, "bench_ui: could not write build/bench_ui.txt\n");
    }
    emit("uimk2 host UI bench\n");
    emit("N=%d per-op warmup=%d discarded global_warmup=%d discarded "
         "stdev=sample(n-1) clock=%s cflags=-O2 sanitize=off\n",
         BENCH_N, BENCH_WARMUP, GLOBAL_WARMUP, clock_name());
    emit("mean_us is us/op. phase is title ox restored before each sample; "
         "long titles use step_x=2.\n");
    emit("%-22s %-20s %5s %10s %10s %10s %10s\n", "scenario", "op", "n",
         "mean_us", "stdev_us", "min_us", "max_us");
    emit("%-22s %-20s %5s %10s %10s %10s %10s\n", "----------------------",
         "--------------------", "-----", "----------", "----------",
         "----------", "----------");
    if (!global_warmup()) {
        if (report != NULL) {
            fclose(report);
        }
        return 1;
    }
    for (i = 0; i < nscene; i++) {
        if (!run_scenario(&SCENES[i])) {
            if (report != NULL) {
                fclose(report);
            }
            return 1;
        }
    }
    emit("sink=%u\n", (unsigned)bench_sink);
    if (report != NULL) {
        emit("report=build/bench_ui.txt\n");
        fclose(report);
        report = NULL;
    }
    return 0;
}
