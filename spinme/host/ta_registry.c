#include "ta_registry.h"

#include <pthread.h>
#include <string.h>

#define TA_REG_MAX 32

typedef struct {
    char name[TA_NAME_MAX];
    ta_enqueue_fn fn;
} ta_reg_slot_t;

static ta_reg_slot_t g_slots[TA_REG_MAX];
static size_t g_n;
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static int g_ready;

static void ensure_init(void) {
    if (!g_ready) {
        g_n = 0;
        memset(g_slots, 0, sizeof(g_slots));
        g_ready = 1;
    }
}

void ta_registry_reset(void) {
    pthread_mutex_lock(&g_mu);
    g_n = 0;
    memset(g_slots, 0, sizeof(g_slots));
    g_ready = 1;
    pthread_mutex_unlock(&g_mu);
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

    pthread_mutex_lock(&g_mu);
    ensure_init();
    for (i = 0; i < g_n; i++) {
        if (strcmp(g_slots[i].name, name) == 0) {
            g_slots[i].fn = fn;
            pthread_mutex_unlock(&g_mu);
            return 0;
        }
    }
    if (g_n >= TA_REG_MAX) {
        pthread_mutex_unlock(&g_mu);
        return -1;
    }
    memcpy(g_slots[g_n].name, name, nlen + 1);
    g_slots[g_n].fn = fn;
    g_n++;
    pthread_mutex_unlock(&g_mu);
    return 0;
}

ta_enqueue_fn ta_registry_lookup(const char *name) {
    size_t i;
    ta_enqueue_fn fn = NULL;

    if (name == NULL) {
        return NULL;
    }
    pthread_mutex_lock(&g_mu);
    ensure_init();
    for (i = 0; i < g_n; i++) {
        if (strcmp(g_slots[i].name, name) == 0) {
            fn = g_slots[i].fn;
            break;
        }
    }
    pthread_mutex_unlock(&g_mu);
    return fn;
}

int ta_registry_post(const char *name, const ta_event_t *ev) {
    ta_enqueue_fn fn;

    fn = ta_registry_lookup(name);
    if (fn == NULL || ev == NULL) {
        return -1;
    }
    return fn(ev);
}
