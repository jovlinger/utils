#include "ta_runtime_cfg.h"

#include "ta_kv.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static ta_runtime_cfg_t g_cfg;
static int g_loaded;

static void put_str(const char *key, const char *val) {
    (void)ta_kv_put(key, val, strlen(val));
}

static void copy_default(ta_runtime_cfg_t *c) {
    memset(c, 0, sizeof(*c));
    strncpy(c->mpd_host, TA_KV_DEF_MPD_HOST, sizeof(c->mpd_host) - 1u);
    strncpy(c->ntp_host, TA_KV_DEF_NTP_HOST, sizeof(c->ntp_host) - 1u);
    strncpy(c->timezone, TA_KV_DEF_TIMEZONE, sizeof(c->timezone) - 1u);
    c->screen_blank_s = (unsigned)atoi(TA_KV_DEF_SCREEN_BLANK_S);
    c->scroll_step = (unsigned)atoi(TA_KV_DEF_SCROLL_STEP);
    c->scroll_ms = (unsigned)atoi(TA_KV_DEF_SCROLL_MS);
}

static void get_str(const char *key, char *dst, size_t cap, const char *def) {
    size_t len = 0;

    if (ta_kv_get(key, dst, cap, &len) == TA_KV_OK && len > 0 &&
        len < cap) {
        dst[len] = '\0';
        return;
    }
    strncpy(dst, def, cap - 1u);
    dst[cap - 1u] = '\0';
}

static unsigned get_u(const char *key, const char *def, unsigned min_v,
                      unsigned max_v) {
    char buf[32];
    size_t len = 0;
    unsigned v;

    if (ta_kv_get(key, buf, sizeof(buf), &len) == TA_KV_OK && len > 0 &&
        len < sizeof(buf)) {
        buf[len] = '\0';
        v = (unsigned)atoi(buf);
    } else {
        v = (unsigned)atoi(def);
    }
    if (v < min_v) {
        v = min_v;
    }
    if (v > max_v) {
        v = max_v;
    }
    return v;
}

void ta_runtime_cfg_put_factory(void) {
    put_str(TA_KV_KEY_MPD_HOST, TA_KV_DEF_MPD_HOST);
    put_str(TA_KV_KEY_NTP_HOST, TA_KV_DEF_NTP_HOST);
    put_str(TA_KV_KEY_TIMEZONE, TA_KV_DEF_TIMEZONE);
    put_str(TA_KV_KEY_SCREEN_BLANK_S, TA_KV_DEF_SCREEN_BLANK_S);
    put_str(TA_KV_KEY_SCROLL_STEP, TA_KV_DEF_SCROLL_STEP);
    put_str(TA_KV_KEY_SCROLL_MS, TA_KV_DEF_SCROLL_MS);
    put_str(TA_KV_KEY_LOGTARGET, "tcp://qnap.local:514");
    put_str(TA_KV_KEY_LOG_URL, "tcp://qnap.local:514");
    put_str(TA_KV_KEY_CONTROLLER, "MPD");
}

int ta_runtime_cfg_load(ta_runtime_cfg_t *out) {
    ta_runtime_cfg_t tmp;

    copy_default(&tmp);
    get_str(TA_KV_KEY_MPD_HOST, tmp.mpd_host, sizeof(tmp.mpd_host),
            TA_KV_DEF_MPD_HOST);
    get_str(TA_KV_KEY_NTP_HOST, tmp.ntp_host, sizeof(tmp.ntp_host),
            TA_KV_DEF_NTP_HOST);
    get_str(TA_KV_KEY_TIMEZONE, tmp.timezone, sizeof(tmp.timezone),
            TA_KV_DEF_TIMEZONE);
    tmp.screen_blank_s =
        get_u(TA_KV_KEY_SCREEN_BLANK_S, TA_KV_DEF_SCREEN_BLANK_S, 5u, 3600u);
    tmp.scroll_step =
        get_u(TA_KV_KEY_SCROLL_STEP, TA_KV_DEF_SCROLL_STEP, 1u, 32u);
    tmp.scroll_ms =
        get_u(TA_KV_KEY_SCROLL_MS, TA_KV_DEF_SCROLL_MS, 10u, 2000u);
    g_cfg = tmp;
    g_loaded = 1;
    if (out != NULL) {
        *out = tmp;
    }
    return 0;
}

const ta_runtime_cfg_t *ta_runtime_cfg(void) {
    if (!g_loaded) {
        (void)ta_runtime_cfg_load(NULL);
    }
    return &g_cfg;
}
