#include "ta_registry.h"

#include "ta_sync.h"

#include <stdio.h>
#include <string.h>

/* Canonical actor names are ASCII-lowercase; strcmp stays case-sensitive. */
static void name_downcase(char *dst, size_t cap, const char *src) {
    size_t i;

    if (dst == NULL || cap == 0) {
        return;
    }
    if (src == NULL) {
        dst[0] = '\0';
        return;
    }
    for (i = 0; i + 1 < cap && src[i] != '\0'; i++) {
        char c = src[i];
        if (c >= 'A' && c <= 'Z') {
            c = (char)(c - 'A' + 'a');
        }
        dst[i] = c;
    }
    dst[i] = '\0';
}


#define TA_REG_MAX 32

typedef struct {
    char name[TA_NAME_MAX];
    ta_enqueue_fn fn;
} ta_reg_slot_t;

static ta_reg_slot_t g_slots[TA_REG_MAX];
static size_t g_n;
static ta_mutex_t g_mu;
static int g_mu_ok;
static int g_ready;

static void ensure_mutex(void) {
    if (!g_mu_ok) {
        if (ta_mutex_init(&g_mu) == 0) {
            g_mu_ok = 1;
        }
    }
}

static void ensure_init(void) {
    if (!g_ready) {
        g_n = 0;
        memset(g_slots, 0, sizeof(g_slots));
        g_ready = 1;
    }
}

void ta_registry_reset(void) {
    ensure_mutex();
    if (!g_mu_ok) {
        return;
    }
    ta_mutex_lock(&g_mu);
    g_n = 0;
    memset(g_slots, 0, sizeof(g_slots));
    g_ready = 1;
    ta_mutex_unlock(&g_mu);
}

int ta_registry_register(const char *name, ta_enqueue_fn fn) {
    size_t i;
    size_t nlen;
    char key[TA_NAME_MAX];

    if (name == NULL || name[0] == '\0' || fn == NULL) {
        return -1;
    }
    name_downcase(key, sizeof(key), name);
    if (key[0] == '\0') {
        return -1;
    }
    nlen = strlen(key);

    ensure_mutex();
    if (!g_mu_ok) {
        return -1;
    }
    ta_mutex_lock(&g_mu);
    ensure_init();
    for (i = 0; i < g_n; i++) {
        if (strcmp(g_slots[i].name, key) == 0) {
            g_slots[i].fn = fn;
            ta_mutex_unlock(&g_mu);
            return 0;
        }
    }
    if (g_n >= TA_REG_MAX) {
        ta_mutex_unlock(&g_mu);
        return -1;
    }
    memcpy(g_slots[g_n].name, key, nlen + 1);
    g_slots[g_n].fn = fn;
    g_n++;
    ta_mutex_unlock(&g_mu);
    return 0;
}

int ta_registry_unregister(const char *name) {
    size_t i;
    char key[TA_NAME_MAX];

    if (name == NULL || name[0] == '\0') {
        return -1;
    }
    name_downcase(key, sizeof(key), name);
    name = key;
    ensure_mutex();
    if (!g_mu_ok) {
        return -1;
    }
    ta_mutex_lock(&g_mu);
    ensure_init();
    for (i = 0; i < g_n; i++) {
        if (strcmp(g_slots[i].name, name) == 0) {
            g_slots[i] = g_slots[g_n - 1];
            memset(&g_slots[g_n - 1], 0, sizeof(g_slots[0]));
            g_n--;
            ta_mutex_unlock(&g_mu);
            return 0;
        }
    }
    ta_mutex_unlock(&g_mu);
    return -1;
}

ta_enqueue_fn ta_registry_lookup(const char *name) {
    size_t i;
    ta_enqueue_fn fn = NULL;
    char key[TA_NAME_MAX];

    if (name == NULL) {
        return NULL;
    }
    name_downcase(key, sizeof(key), name);
    name = key;
    ensure_mutex();
    if (!g_mu_ok) {
        return NULL;
    }
    ta_mutex_lock(&g_mu);
    ensure_init();
    for (i = 0; i < g_n; i++) {
        if (strcmp(g_slots[i].name, name) == 0) {
            fn = g_slots[i].fn;
            break;
        }
    }
    ta_mutex_unlock(&g_mu);
    return fn;
}

size_t ta_registry_copy_names(char *dst, size_t stride, size_t max) {
    size_t i;
    size_t n;

    if (dst == NULL || stride < TA_NAME_MAX || max == 0) {
        return 0;
    }
    ensure_mutex();
    if (!g_mu_ok) {
        return 0;
    }
    ta_mutex_lock(&g_mu);
    ensure_init();
    n = g_n;
    if (n > max) {
        n = max;
    }
    for (i = 0; i < n; i++) {
        memcpy(dst + i * stride, g_slots[i].name, TA_NAME_MAX);
    }
    ta_mutex_unlock(&g_mu);
    return n;
}

int ta_registry_post(const char *name, const ta_event_envelope_t *env) {
    ta_enqueue_fn fn;

    fn = ta_registry_lookup(name);
    if (fn == NULL || env == NULL) {
        return -1;
    }
    return fn(env);
}

int ta_debug_status_reply(const ta_event_envelope_t *req, const char *actor_name,
                          const char *text) {
    ta_event_envelope_t reply;

    if (req == NULL || actor_name == NULL || actor_name[0] == '\0') {
        return -1;
    }
    ta_env_clear(&reply);
    if (ta_env_set_src(&reply, actor_name) != 0) {
        return -1;
    }
    reply.session_id = req->session_id;
    reply.event.type = TA_EV_DEBUG_STATUS;
    if (text == NULL) {
        text = "";
    }
    snprintf(reply.event.u.debug_status.text,
             sizeof(reply.event.u.debug_status.text), "%s", text);
    return ta_registry_post("controller", &reply);
}
