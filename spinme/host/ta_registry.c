#include "ta_registry.h"

#include "ta_sync.h"

#include <string.h>

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

    if (name == NULL || name[0] == '\0' || fn == NULL) {
        return -1;
    }
    nlen = strlen(name);
    if (nlen >= TA_NAME_MAX) {
        return -1;
    }

    ensure_mutex();
    if (!g_mu_ok) {
        return -1;
    }
    ta_mutex_lock(&g_mu);
    ensure_init();
    for (i = 0; i < g_n; i++) {
        if (strcmp(g_slots[i].name, name) == 0) {
            g_slots[i].fn = fn;
            ta_mutex_unlock(&g_mu);
            return 0;
        }
    }
    if (g_n >= TA_REG_MAX) {
        ta_mutex_unlock(&g_mu);
        return -1;
    }
    memcpy(g_slots[g_n].name, name, nlen + 1);
    g_slots[g_n].fn = fn;
    g_n++;
    ta_mutex_unlock(&g_mu);
    return 0;
}

ta_enqueue_fn ta_registry_lookup(const char *name) {
    size_t i;
    ta_enqueue_fn fn = NULL;

    if (name == NULL) {
        return NULL;
    }
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

int ta_registry_post(const char *name, const ta_event_envelope_t *env) {
    ta_enqueue_fn fn;

    fn = ta_registry_lookup(name);
    if (fn == NULL || env == NULL) {
        return -1;
    }
    return fn(env);
}
