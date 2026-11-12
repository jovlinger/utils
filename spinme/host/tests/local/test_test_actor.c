/* Dev Test actor: RUN one / suite / timing -> DONE with counts + elapsed. */
#include "ta_event.h"
#include "ta_follow_chrome.h"
#include "ta_registry.h"
#include "ta_test_actor.h"
#include "ta_uilayout.h"

#include <stdio.h>
#include <string.h>

int ta_glass_installed(void) { return 0; }
const ta_follow_chrome_t *ta_glass_chrome(void) { return NULL; }
const ta_pack66_t *ta_glass_base_pixels(void) { return NULL; }
void ta_glass_panel_size(uint16_t *out_w, uint16_t *out_h) {
    if (out_w != NULL) {
        *out_w = 0;
    }
    if (out_h != NULL) {
        *out_h = 0;
    }
}
const char *ta_glass_text(uint8_t field) {
    (void)field;
    return "";
}
int ta_glass_polled(void) { return 0; }
int ta_glass_desired(void) { return 0; }
int ta_glass_playing(void) { return 0; }
unsigned ta_glass_page(void) { return 0; }

static int failures;
static int checks;

#define CHECK(cond)                                                            \
    do {                                                                       \
        checks++;                                                              \
        if (!(cond)) {                                                         \
            failures++;                                                        \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__,   \
                    #cond);                                                    \
        }                                                                      \
    } while (0)

static ta_event_envelope_t g_last;
static int g_got;

static int sink(const ta_event_envelope_t *env) {
    if (env == NULL) {
        return -1;
    }
    g_last = *env;
    g_got++;
    return 0;
}

int main(void) {
    const ta_test_stats_t *st;
    const ta_test_done_t *done;

    ta_registry_reset();
    ta_test_start();
    CHECK(ta_registry_register("Origin", sink) == 0);

    g_got = 0;
    CHECK(ta_test_post_run(TA_TEST_MODE_ONE, "smoke", "Origin", 7) == 0);
    CHECK(g_got == 1);
    CHECK(g_last.event.type == TA_EV_TEST_DONE);
    CHECK(g_last.session_id == 7);
    done = &g_last.event.u.test_done;
    CHECK(done->status == 0);
    CHECK(done->n_ran == 1);
    CHECK(done->n_fail == 0);
    CHECK(strcmp(done->selector, "smoke") == 0);

    g_got = 0;
    CHECK(ta_test_post_run(TA_TEST_MODE_SUITE, "smoke", "Origin", 8) == 0);
    CHECK(g_got == 1);
    done = &g_last.event.u.test_done;
    CHECK(done->status == 0);
    CHECK(done->n_ran == 1);
    CHECK(done->n_fail == 0);

    g_got = 0;
    CHECK(ta_test_post_run(TA_TEST_MODE_TIMING, "smoke", "Origin", 9) == 0);
    CHECK(g_got == 1);
    done = &g_last.event.u.test_done;
    CHECK(done->status == 0);
    CHECK(done->n_ran == 1);
    /* Wall time may be 0 on a fast box; still a filled field. */
    CHECK(done->elapsed_ms < 60000u);

    g_got = 0;
    CHECK(ta_test_post_run(TA_TEST_MODE_ONE, "no_such_test", "Origin", 10) !=
          0);
    CHECK(g_got == 1);
    done = &g_last.event.u.test_done;
    CHECK(done->status != 0);
    CHECK(done->n_fail >= 1);

    st = ta_test_stats();
    CHECK(st->runs >= 4);
    CHECK(st->dones >= 4);

    if (failures) {
        fprintf(stderr, "test_test_actor: %d/%d checks failed\n", failures,
                checks);
        return 1;
    }
    printf("test_test_actor: %d checks ok\n", checks);
    return 0;
}
