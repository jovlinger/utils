#include "ta_init.h"

#include "ta_event.h"

#include <stddef.h>
#include <string.h>

#define TA_INIT_MAX 16

typedef struct {
    char name[TA_NAME_MAX];
    ta_entry_fn start;
} ta_init_entry_t;

static ta_init_entry_t g_entries[TA_INIT_MAX];
static size_t g_n;

void ta_init_reset(void) {
    memset(g_entries, 0, sizeof(g_entries));
    g_n = 0;
}

int ta_init_add_entry(const char *name, ta_entry_fn start) {
    size_t nlen;

    if (name == NULL || name[0] == '\0' || start == NULL) {
        return -1;
    }
    nlen = strlen(name);
    if (nlen >= TA_NAME_MAX || g_n >= TA_INIT_MAX) {
        return -1;
    }
    memcpy(g_entries[g_n].name, name, nlen + 1);
    g_entries[g_n].start = start;
    g_n++;
    return 0;
}

void ta_init_run_entries(void) {
    size_t i;

    for (i = 0; i < g_n; i++) {
        g_entries[i].start();
    }
}

size_t ta_init_entry_count(void) {
    return g_n;
}
