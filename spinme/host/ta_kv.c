#include "ta_kv.h"

#include <string.h>

typedef struct {
    int used;
    char key[TA_KV_KEY_MAX];
    size_t len;
    uint8_t val[TA_KV_VAL_MAX];
} ta_kv_slot_t;

static ta_kv_slot_t g_slots[TA_KV_SLOTS];

void ta_kv_reset(void) {
    memset(g_slots, 0, sizeof(g_slots));
}

static int key_ok(const char *key) {
    size_t n;

    if (key == NULL || key[0] == '\0') {
        return 0;
    }
    n = strlen(key);
    return n > 0 && n < TA_KV_KEY_MAX;
}

static ta_kv_slot_t *find(const char *key) {
    size_t i;

    for (i = 0; i < TA_KV_SLOTS; i++) {
        if (g_slots[i].used && strcmp(g_slots[i].key, key) == 0) {
            return &g_slots[i];
        }
    }
    return NULL;
}

static ta_kv_slot_t *find_free(void) {
    size_t i;

    for (i = 0; i < TA_KV_SLOTS; i++) {
        if (!g_slots[i].used) {
            return &g_slots[i];
        }
    }
    return NULL;
}

int ta_kv_has(const char *key) {
    if (!key_ok(key)) {
        return 0;
    }
    return find(key) != NULL ? 1 : 0;
}

ta_kv_status_t ta_kv_get_len(const char *key, size_t *out_len) {
    ta_kv_slot_t *s;

    if (!key_ok(key) || out_len == NULL) {
        return TA_KV_BAD_ARG;
    }
    s = find(key);
    if (s == NULL) {
        return TA_KV_MISSING;
    }
    *out_len = s->len;
    return TA_KV_OK;
}

ta_kv_status_t ta_kv_get(const char *key, void *dst, size_t dst_cap,
                         size_t *out_len) {
    ta_kv_slot_t *s;

    if (!key_ok(key) || out_len == NULL) {
        return TA_KV_BAD_ARG;
    }
    s = find(key);
    if (s == NULL) {
        return TA_KV_MISSING;
    }
    *out_len = s->len;
    if (dst_cap < s->len) {
        return TA_KV_TOO_SMALL;
    }
    if (s->len > 0) {
        if (dst == NULL) {
            return TA_KV_BAD_ARG;
        }
        memcpy(dst, s->val, s->len);
    }
    return TA_KV_OK;
}

ta_kv_status_t ta_kv_put(const char *key, const void *src, size_t len) {
    ta_kv_slot_t *s;
    size_t klen;

    if (!key_ok(key) || len > TA_KV_VAL_MAX) {
        return TA_KV_BAD_ARG;
    }
    if (len > 0 && src == NULL) {
        return TA_KV_BAD_ARG;
    }
    s = find(key);
    if (s == NULL) {
        s = find_free();
        if (s == NULL) {
            return TA_KV_FULL;
        }
        klen = strlen(key);
        memcpy(s->key, key, klen + 1);
        s->used = 1;
    }
    if (len > 0) {
        memcpy(s->val, src, len);
    }
    s->len = len;
    return TA_KV_OK;
}

ta_kv_status_t ta_kv_delete(const char *key) {
    ta_kv_slot_t *s;

    if (!key_ok(key)) {
        return TA_KV_BAD_ARG;
    }
    s = find(key);
    if (s == NULL) {
        return TA_KV_MISSING;
    }
    memset(s, 0, sizeof(*s));
    return TA_KV_OK;
}

ta_kv_status_t ta_config_get_controller(char *dst, size_t dst_cap,
                                        size_t *out_len) {
    return ta_kv_get(TA_KV_KEY_CONTROLLER, dst, dst_cap, out_len);
}

ta_kv_status_t ta_config_put_controller(const char *name) {
    size_t n;

    if (name == NULL) {
        return TA_KV_BAD_ARG;
    }
    n = strlen(name);
    return ta_kv_put(TA_KV_KEY_CONTROLLER, name, n);
}
