#include "ta_all.h"

#include "ta_event.h"
#include "ta_registry.h"

#include <string.h>

#define TA_ALL_NAME_CAP 32

int ta_all_broadcast_perform_init(const char *src) {
    char names[TA_ALL_NAME_CAP][TA_NAME_MAX];
    size_t n;
    size_t i;
    int ok;

    if (src == NULL || src[0] == '\0') {
        src = "Init";
    }
    n = ta_registry_copy_names(&names[0][0], TA_NAME_MAX, TA_ALL_NAME_CAP);
    ok = 0;
    for (i = 0; i < n; i++) {
        ta_event_envelope_t env;

        ta_env_clear(&env);
        if (ta_env_set_src(&env, src) != 0) {
            continue;
        }
        env.event.type = TA_EV_ALL_PERFORM_INIT;
        if (ta_registry_post(names[i], &env) == 0) {
            ok++;
        }
    }
    return ok;
}
