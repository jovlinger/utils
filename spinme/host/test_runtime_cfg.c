/* Runtime KV settings: factory defaults load; override then reload. */
#include "ta_kv.h"
#include "ta_runtime_cfg.h"

#include <stdio.h>
#include <string.h>

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

int main(void) {
    ta_runtime_cfg_t cfg;

    ta_kv_install_factory();
    CHECK(ta_runtime_cfg_load(&cfg) == 0);
    CHECK(strcmp(cfg.mpd_host, TA_KV_DEF_MPD_HOST) == 0);
    CHECK(strcmp(cfg.ntp_host, TA_KV_DEF_NTP_HOST) == 0);
    CHECK(strcmp(cfg.timezone, TA_KV_DEF_TIMEZONE) == 0);
    CHECK(cfg.screen_blank_s == 30u);
    CHECK(cfg.scroll_step == 2u);
    CHECK(cfg.scroll_ms == 40u);

    CHECK(ta_kv_put(TA_KV_KEY_MPD_HOST, "mpd.lan", 7) == TA_KV_OK);
    CHECK(ta_kv_put(TA_KV_KEY_SCROLL_MS, "80", 2) == TA_KV_OK);
    CHECK(ta_runtime_cfg_load(&cfg) == 0);
    CHECK(strcmp(cfg.mpd_host, "mpd.lan") == 0);
    CHECK(cfg.scroll_ms == 80u);

    if (failures != 0) {
        fprintf(stderr, "test_runtime_cfg: %d/%d checks failed\n", failures,
                checks);
        return 1;
    }
    printf("test_runtime_cfg: %d checks ok\n", checks);
    return 0;
}
