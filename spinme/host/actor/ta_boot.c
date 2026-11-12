#include "ta_boot.h"

#include "ta_kv.h"

#include <string.h>

static ta_actor_t g_actors[TA_BOOT_MAX];
static int g_n;

int ta_boot_running_count(void) {
    return g_n;
}

int ta_boot_from_kv(void) {
    size_t n;
    size_t i;

    if (g_n != 0) {
        return -1;
    }
    n = ta_kv_roster_count();
    if (n > TA_BOOT_MAX) {
        return -1;
    }
    for (i = 0; i < n; i++) {
        char name[TA_KV_KEY_MAX];
        uint8_t blob[TA_KV_VAL_MAX];
        size_t nlen;
        size_t blen;

        if (ta_kv_roster_at(i, name, sizeof(name) - 1, &nlen) != TA_KV_OK) {
            ta_boot_exit_all();
            return -1;
        }
        name[nlen] = '\0';
        if (ta_kv_get(name, blob, sizeof(blob), &blen) != TA_KV_OK || blen == 0) {
            ta_boot_exit_all();
            return -1;
        }
        /* Stub load: the blob bytes are the image. Host does not map ELF yet.
         * A non-empty blob is enough to call init().
         */
        (void)blob;
        if (ta_actor_init(&g_actors[g_n], name) != 0) {
            ta_boot_exit_all();
            return -1;
        }
        g_n++;
    }
    return g_n;
}

void ta_boot_exit_all(void) {
    while (g_n > 0) {
        g_n--;
        ta_actor_exit(&g_actors[g_n]);
    }
}
