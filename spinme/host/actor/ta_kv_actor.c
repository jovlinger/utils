#include "ta_kv_actor.h"

#include "ta_event.h"
#include "ta_registry.h"

#include <string.h>

int ta_kv_actor_set(const char *key, const void *src, size_t n) {
    if (ta_kv_put(key, src, n) != TA_KV_OK) {
        return -1;
    }
    return 0;
}

int ta_kv_actor_get(const char *reply_to, const char *key) {
    uint8_t buf[TA_ALL_INFORM_MAX];
    size_t len;
    ta_kv_status_t st;
    ta_event_envelope_t env;
    size_t copy_n;

    if (reply_to == NULL || key == NULL) {
        return -1;
    }
    len = 0;
    st = ta_kv_get(key, buf, sizeof(buf), &len);
    if (st != TA_KV_OK && st != TA_KV_MISSING && st != TA_KV_TOO_SMALL) {
        return -1;
    }
    copy_n = 0;
    if (st == TA_KV_OK) {
        copy_n = len;
    }
    ta_env_clear(&env);
    if (ta_env_set_src(&env, "KV") != 0) {
        return -1;
    }
    if (ta_event_set_all_inform_result(&env.event, (uint8_t)st, key, buf,
                                      copy_n) != 0) {
        return -1;
    }
    return ta_registry_post(reply_to, &env);
}
