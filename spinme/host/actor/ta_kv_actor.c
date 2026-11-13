#include "ta_kv_actor.h"

#include "ta_event.h"
#include "ta_net_events.h"
#include "ta_net_http_event.h"
#include "ta_registry.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int offer_http_text(const ta_event_envelope_t *req, unsigned status,
                           const char *text) {
    ta_event_envelope_t reply;
    size_t n;

    if (req == NULL) {
        return -1;
    }
    if (text == NULL) {
        text = "";
    }
    n = strlen(text);
    if (n > TA_NET_HTTP_REPLY_MAX) {
        ta_net_http_offer_blob(req->session_id, status, (const uint8_t *)text,
                               n);
        return 0;
    }
    ta_env_clear(&reply);
    (void)ta_env_set_src(&reply, TA_KVCONFIG_NAME);
    reply.session_id = req->session_id;
    reply.event.type = TA_EV_NET_HTTP_REPLY;
    reply.event.u.net_http_reply.http_status = (uint16_t)status;
    reply.event.u.net_http_reply.n = (uint16_t)n;
    if (n > 0) {
        memcpy(reply.event.u.net_http_reply.bytes, text, n);
    }
    ta_net_http_offer_reply(&reply);
    return 0;
}

static int handle_get(const ta_event_envelope_t *env) {
    uint8_t buf[TA_KV_VAL_MAX];
    size_t len;
    uint32_t ty;
    ta_kv_status_t st;
    char out[TA_KV_VAL_MAX + 16];
    int n;

    st = ta_kv_get_type(env->event.u.kv_get.key, &ty);
    if (st == TA_KV_MISSING) {
        return offer_http_text(env, 404u, "missing");
    }
    if (st != TA_KV_OK) {
        return offer_http_text(env, 400u, "bad");
    }
    st = ta_kv_get(env->event.u.kv_get.key, buf, sizeof(buf), &len);
    if (st != TA_KV_OK) {
        return offer_http_text(env, 400u, "bad");
    }
    /* Body: "type=<n>\n" then raw value bytes (ASCII for str/int/bool). */
    n = snprintf(out, sizeof(out), "type=%u\n", (unsigned)ty);
    if (n < 0 || (size_t)n >= sizeof(out)) {
        return offer_http_text(env, 500u, "overflow");
    }
    if ((size_t)n + len >= sizeof(out)) {
        return offer_http_text(env, 500u, "overflow");
    }
    memcpy(out + (size_t)n, buf, len);
    out[(size_t)n + len] = '\0';
    return offer_http_text(env, 200u, out);
}

static int handle_set(const ta_event_envelope_t *env) {
    const ta_kv_set_t *body;
    uint32_t ty;
    ta_kv_status_t st;
    const char *val;
    size_t vlen;

    body = &env->event.u.kv_set;
    ty = (uint32_t)body->type;
    val = body->value;
    vlen = strlen(val);
    if (ty == TA_KV_VTYPE_BOOL) {
        uint8_t b;

        b = (val[0] == '1' || val[0] == 't' || val[0] == 'T') ? 1u : 0u;
        st = ta_kv_put_typed(body->key, TA_KV_VTYPE_BOOL, &b, 1);
    } else if (ty == TA_KV_VTYPE_INT) {
        int32_t i;
        uint8_t buf[4];

        i = (int32_t)atoi(val);
        buf[0] = (uint8_t)((uint32_t)i & 0xffu);
        buf[1] = (uint8_t)(((uint32_t)i >> 8) & 0xffu);
        buf[2] = (uint8_t)(((uint32_t)i >> 16) & 0xffu);
        buf[3] = (uint8_t)(((uint32_t)i >> 24) & 0xffu);
        st = ta_kv_put_typed(body->key, TA_KV_VTYPE_INT, buf, 4);
    } else if (ty == TA_KV_VTYPE_STR) {
        st = ta_kv_put_typed(body->key, TA_KV_VTYPE_STR, val, vlen);
    } else if (ty == TA_KV_VTYPE_BLOB || ty == TA_KV_VTYPE_EXECUTABLE ||
               ty == TA_KV_VTYPE_BITMAP) {
        st = ta_kv_put_typed(body->key, ty, val, vlen);
    } else {
        return offer_http_text(env, 400u, "bad_type");
    }
    if (st != TA_KV_OK) {
        return offer_http_text(env, 400u, "fail");
    }
    return offer_http_text(env, 200u, "ok");
}

static int handle_list(const ta_event_envelope_t *env) {
    char body[TA_NET_HTTP_REPLY_MAX * 4];
    size_t o;
    size_t i;
    size_t n;

    n = ta_kv_count();
    o = 0;
    body[0] = '\0';
    for (i = 0; i < n; i++) {
        char key[TA_KV_KEY_MAX];
        size_t klen;
        int wrote;

        if (ta_kv_key_at(i, key, sizeof(key), &klen) != TA_KV_OK) {
            break;
        }
        if (o > 0) {
            if (o + 1 >= sizeof(body)) {
                break;
            }
            body[o++] = ',';
            body[o] = '\0';
        }
        wrote = snprintf(body + o, sizeof(body) - o, "%s", key);
        if (wrote < 0 || (size_t)wrote >= sizeof(body) - o) {
            break;
        }
        o += (size_t)wrote;
    }
    return offer_http_text(env, 200u, body);
}

static int handle_delete(const ta_event_envelope_t *env) {
    ta_kv_status_t st;

    st = ta_kv_delete(env->event.u.kv_delete.key);
    if (st == TA_KV_MISSING) {
        return offer_http_text(env, 404u, "missing");
    }
    if (st != TA_KV_OK) {
        return offer_http_text(env, 400u, "fail");
    }
    return offer_http_text(env, 200u, "ok");
}

void ta_kvconfig_reset(void) {
    /* Image lifetime is owned by ta_kv_*; actor has no extra state. */
}

int ta_kvconfig_enqueue(const ta_event_envelope_t *env) {
    if (env == NULL) {
        return -1;
    }
    if (env->event.type == TA_EV_DEBUG_STATUS) {
        return ta_debug_status_reply(env, TA_KVCONFIG_NAME, "ok");
    }
    if (env->event.type == TA_EV_KV_GET) {
        return handle_get(env);
    }
    if (env->event.type == TA_EV_KV_SET) {
        return handle_set(env);
    }
    if (env->event.type == TA_EV_KV_LIST) {
        return handle_list(env);
    }
    if (env->event.type == TA_EV_KV_DELETE) {
        return handle_delete(env);
    }
    return -1;
}

void ta_kvconfig_start(void) {
    (void)ta_registry_register(TA_KVCONFIG_NAME, ta_kvconfig_enqueue);
}

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
    if (ta_env_set_src(&env, TA_KVCONFIG_NAME) != 0) {
        return -1;
    }
    if (ta_event_set_all_inform_result(&env.event, (uint8_t)st, key, buf,
                                      copy_n) != 0) {
        return -1;
    }
    return ta_registry_post(reply_to, &env);
}
