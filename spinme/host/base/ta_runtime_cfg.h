/* Runtime settings stored in KV; factory image seeds defaults.
 * Call ta_runtime_cfg_load() at boot / perform_init; getters read the cache.
 */
#ifndef SPINME_TA_RUNTIME_CFG_H
#define SPINME_TA_RUNTIME_CFG_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TA_KV_KEY_MPD_HOST "mpd_host"
#define TA_KV_KEY_NTP_HOST "ntp_host"
#define TA_KV_KEY_TIMEZONE "timezone"
#define TA_KV_KEY_SCREEN_BLANK_S "screen_blank_s"
#define TA_KV_KEY_SCROLL_STEP "title_scroll_step"
#define TA_KV_KEY_SCROLL_MS "title_scroll_ms"

#define TA_KV_DEF_MPD_HOST "miniDSP-SHD.local"
#define TA_KV_DEF_NTP_HOST "pool.ntp.org"
#define TA_KV_DEF_TIMEZONE "EST5EDT,M3.2.0/2,M11.1.0/2"
#define TA_KV_DEF_SCREEN_BLANK_S "30"
#define TA_KV_DEF_SCROLL_STEP "2"
#define TA_KV_DEF_SCROLL_MS "40"

#define TA_RUNTIME_HOST_MAX 96
#define TA_RUNTIME_TZ_MAX 64

typedef struct ta_runtime_cfg {
    char mpd_host[TA_RUNTIME_HOST_MAX];
    char ntp_host[TA_RUNTIME_HOST_MAX];
    char timezone[TA_RUNTIME_TZ_MAX];
    unsigned screen_blank_s;
    unsigned scroll_step;
    unsigned scroll_ms;
} ta_runtime_cfg_t;

/* Seed well-known config keys into the live KV image (idempotent puts). */
void ta_runtime_cfg_put_factory(void);

/* Read KV into out (and into the process cache). Missing keys use defaults. */
int ta_runtime_cfg_load(ta_runtime_cfg_t *out);

/* Last successful load (defaults if never loaded). */
const ta_runtime_cfg_t *ta_runtime_cfg(void);

#ifdef __cplusplus
}
#endif

#endif
