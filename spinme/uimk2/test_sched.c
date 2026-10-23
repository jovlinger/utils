/* Host tests for the uimk2 scheduler model. */
#include "uimk2_sched.h"

#include <stdio.h>
#include <stdlib.h>

static int failures;
static int checks;

#define CHECK(cond)                                                        \
    do {                                                                   \
        checks++;                                                          \
        if (!(cond)) {                                                     \
            failures++;                                                    \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__,         \
                    __LINE__, #cond);                                      \
        }                                                                  \
    } while (0)

static void drain_work(uimk2_sched *s) {
    uimk2_work_item w;
    while (uimk2_sched_work_pop(s, &w)) {
    }
}

static void test_volume_replace_keeps_order(void) {
    uimk2_sched s;
    uimk2_work_item w;
    uimk2_sched_init(&s);
    CHECK(uimk2_sched_post_poll(&s));
    CHECK(uimk2_sched_post_volume(&s, 1));
    CHECK(uimk2_sched_post_toggle(&s));
    CHECK(uimk2_sched_post_volume(&s, 9));
    CHECK(s.work_len == 3);
    CHECK(uimk2_sched_work_pop(&s, &w) && w.kind == UIMK2_WORK_POLL);
    CHECK(uimk2_sched_work_pop(&s, &w) && w.kind == UIMK2_WORK_SET_VOLUME &&
          w.volume == 9);
    CHECK(uimk2_sched_work_pop(&s, &w) && w.kind == UIMK2_WORK_TOGGLE);
    CHECK(!uimk2_sched_work_pop(&s, &w));
}

static void test_full_queue(void) {
    uimk2_sched s;
    uint32_t i;
    uimk2_work_item w;
    uimk2_sched_init(&s);
    CHECK(uimk2_sched_post_poll(&s));
    for (i = 0; i < UIMK2_SCHED_DEPTH - 1u; i++) {
        CHECK(uimk2_sched_post_toggle(&s));
    }
    CHECK(s.work_len == UIMK2_SCHED_DEPTH);
    CHECK(!uimk2_sched_post_toggle(&s));
    CHECK(s.work_len == UIMK2_SCHED_DEPTH);
    CHECK(uimk2_sched_post_poll(&s)); /* replaces */
    CHECK(s.work_len == UIMK2_SCHED_DEPTH);
    CHECK(!uimk2_sched_post_volume(&s, 3)); /* no volume slot, full */
    CHECK(uimk2_sched_work_pop(&s, &w) && w.kind == UIMK2_WORK_POLL);
    CHECK(uimk2_sched_post_volume(&s, 3)); /* room again, appended */
    CHECK(s.work[s.work_len - 1].kind == UIMK2_WORK_SET_VOLUME);
}

static void test_scroll_coalesce(void) {
    uimk2_sched s;
    uimk2_ui_item u;
    uimk2_sched_init(&s);
    s.scrolling = true;
    CHECK(uimk2_sched_detent(&s, 10, 2, 0, 50, 7));
    CHECK(uimk2_sched_detent(&s, 20, 3, 1, 50, 7));
    CHECK(s.work_len == 0);
    CHECK(s.ui_len == 1);
    CHECK(s.ui[0].kind == UIMK2_UI_SCROLL && s.ui[0].viewport == 7 &&
          s.ui[0].dx == 5 && s.ui[0].dy == 1);
    CHECK(uimk2_sched_detent(&s, 30, -5, -1, 50, 7));
    CHECK(s.ui_len == 0);
    CHECK(s.work_len == 0);
    CHECK(!uimk2_sched_ui_pop(&s, &u));
}

static void test_scroll_remove_closes_gap(void) {
    uimk2_sched s;
    uimk2_ui_item u;
    uimk2_sched_init(&s);
    CHECK(uimk2_sched_post_knob(&s, 1));
    CHECK(uimk2_sched_post_scroll(&s, 4, 1, 1));
    CHECK(uimk2_sched_snapshot(&s));
    CHECK(uimk2_sched_post_scroll(&s, 5, 2, 2));
    CHECK(uimk2_sched_post_scroll(&s, 4, -1, -1));
    CHECK(s.ui_len == 3);
    CHECK(uimk2_sched_ui_pop(&s, &u) && u.kind == UIMK2_UI_KNOB);
    CHECK(uimk2_sched_ui_pop(&s, &u) && u.kind == UIMK2_UI_SNAPSHOT);
    CHECK(uimk2_sched_ui_pop(&s, &u) && u.kind == UIMK2_UI_SCROLL &&
          u.viewport == 5);
}

static void test_no_coalesce_ui(void) {
    uimk2_sched s;
    uimk2_sched_init(&s);
    CHECK(uimk2_sched_snapshot(&s));
    CHECK(uimk2_sched_snapshot(&s));
    CHECK(uimk2_sched_post_knob(&s, 1));
    CHECK(uimk2_sched_post_knob(&s, 1));
    CHECK(uimk2_sched_touch(&s, 5, 1, 2));
    CHECK(uimk2_sched_touch(&s, 6, 1, 2));
    CHECK(s.ui_len == 6);
}

static void test_follow_detent(void) {
    uimk2_sched s;
    uimk2_work_item w;
    uimk2_sched_init(&s);
    CHECK(!s.scrolling);
    CHECK(uimk2_sched_detent(&s, 100, 2, 3, 42, 7));
    CHECK(s.ui_len == 0);
    CHECK(s.work_len == 1);
    CHECK(uimk2_sched_work_pop(&s, &w) && w.kind == UIMK2_WORK_SET_VOLUME &&
          w.volume == 42);
}

static void test_snapshot_clocks(void) {
    uimk2_sched s;
    uimk2_sched_init(&s);
    CHECK(uimk2_sched_detent(&s, 500, 0, 0, 1, 0));
    drain_work(&s);
    CHECK(uimk2_sched_tick(&s, 1500)); /* gap -> 2000 */
    CHECK(s.poll_gap_ms == 2000);
    CHECK(uimk2_sched_snapshot(&s));
    CHECK(s.last_activity == 500);
    CHECK(s.poll_gap_ms == 2000);
    CHECK(s.last_poll == 1500);
    CHECK(s.awake);
}

static void test_wake_and_backoff(void) {
    uimk2_sched s;
    uimk2_work_item w;
    uint32_t t0 = 40000;
    uimk2_sched_init(&s);
    CHECK(s.awake && s.poll_gap_ms == 1000 && s.last_activity == 0 &&
          s.last_poll == 0 && s.work_len == 0 && s.ui_len == 0);
    CHECK(!uimk2_sched_tick(&s, 30000)); /* falls asleep */
    CHECK(!s.awake);
    CHECK(s.work_len == 0);
    CHECK(!uimk2_sched_tick(&s, 31000)); /* asleep: nothing */
    CHECK(s.work_len == 0);

    CHECK(uimk2_sched_detent(&s, t0, 0, 0, 5, 0));
    CHECK(s.awake);
    CHECK(s.poll_gap_ms == 1000);
    CHECK(s.last_poll == t0 && s.last_activity == t0);
    CHECK(s.work_len == 2); /* wake Poll, SetVolume */
    CHECK(uimk2_sched_work_pop(&s, &w) && w.kind == UIMK2_WORK_POLL);
    drain_work(&s);

    CHECK(!uimk2_sched_tick(&s, t0 + 999));
    CHECK(s.work_len == 0);
    CHECK(uimk2_sched_tick(&s, t0 + 1000));
    CHECK(s.work_len == 1 && s.work[0].kind == UIMK2_WORK_POLL);
    CHECK(s.poll_gap_ms == 2000);
    CHECK(s.last_activity == t0);
    drain_work(&s);

    CHECK(!uimk2_sched_tick(&s, t0 + 2999));
    CHECK(uimk2_sched_tick(&s, t0 + 3000));
    CHECK(s.poll_gap_ms == 4000);
    CHECK(uimk2_sched_tick(&s, t0 + 7000));
    CHECK(s.poll_gap_ms == 8000);
    CHECK(uimk2_sched_tick(&s, t0 + 15000));
    CHECK(s.poll_gap_ms == 16000);
    drain_work(&s);

    /* Keep awake so the cap can be observed holding. last_activity must
     * not sit in the future of the tick, or the unsigned subtract wraps. */
    s.last_activity = t0 + 15000;
    CHECK(!uimk2_sched_tick(&s, t0 + 30999));
    CHECK(uimk2_sched_tick(&s, t0 + 31000));
    CHECK(s.poll_gap_ms == 16000);
    s.last_activity = t0 + 47000;
    CHECK(uimk2_sched_tick(&s, t0 + 47000));
    CHECK(s.poll_gap_ms == 16000);
}

static void test_wake_no_double_gap_and_awake_restart(void) {
    uimk2_sched s;
    uimk2_sched_init(&s);
    CHECK(uimk2_sched_touch(&s, 300, 1, 2));
    CHECK(s.work_len == 0); /* already awake: no extra poll */
    CHECK(s.last_poll == 300 && s.last_activity == 300);
    CHECK(s.ui_len == 1 && s.ui[0].kind == UIMK2_UI_TOUCH);
    CHECK(uimk2_sched_tick(&s, 1300));
    CHECK(s.poll_gap_ms == 2000);
    CHECK(uimk2_sched_touch(&s, 1400, 1, 2));
    CHECK(s.poll_gap_ms == 1000);
    CHECK(s.last_poll == 1400);
}

static void test_screen_off(void) {
    uimk2_sched s;
    uimk2_sched_init(&s);
    CHECK(uimk2_sched_detent(&s, 1000, 0, 0, 1, 0));
    drain_work(&s);
    CHECK(!uimk2_sched_tick(&s, 1999)); /* still inside the first poll gap */
    s.last_poll = 30999; /* suppress poll so only the screen clock decides */
    CHECK(!uimk2_sched_tick(&s, 30999));
    CHECK(s.awake);
    CHECK(!uimk2_sched_tick(&s, 31000)); /* 30000 after last_activity */
    CHECK(!s.awake);
    CHECK(s.work_len == 0);
}

static void test_tick_wraparound(void) {
    uimk2_sched s;
    uimk2_sched_init(&s);
    CHECK(uimk2_sched_detent(&s, 0xFFFFFF00u, 0, 0, 1, 0));
    drain_work(&s);
    CHECK(uimk2_sched_tick(&s, 0xFFFFFF00u + 1000u)); /* wraps past 0 */
    CHECK(s.poll_gap_ms == 2000);
}

int main(void) {
    test_volume_replace_keeps_order();
    test_full_queue();
    test_scroll_coalesce();
    test_scroll_remove_closes_gap();
    test_no_coalesce_ui();
    test_follow_detent();
    test_snapshot_clocks();
    test_wake_and_backoff();
    test_wake_no_double_gap_and_awake_restart();
    test_screen_off();
    test_tick_wraparound();
    printf("test_sched: %d checks, %d failures\n", checks, failures);
    return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
