#include "ta_router.h"

#include "ta_registry.h"

#include <stdio.h>
#include <string.h>

static char g_target[TA_NAME_MAX];

void ta_router_reset(void) {
    g_target[0] = '\0';
}

const char *ta_router_current_target(void) {
    return g_target;
}

static int set_route(const ta_event_envelope_t *env) {
    const char *name = env->event.u.ctrl_set_route.target;

    if (name[0] == '\0') {
        fprintf(stderr, "ERROR: SetRoute bad target\n");
        return -1;
    }
    memcpy(g_target, name, TA_NAME_MAX);
    return 0;
}

int ta_router_enqueue(const ta_event_envelope_t *env) {
    if (env == NULL) {
        return -1;
    }
    if (env->event.type == TA_EV_SET_ROUTE) {
        return set_route(env);
    }
    if (g_target[0] == '\0') {
        fprintf(stderr, "ERROR: Controller has no route\n");
        return -1;
    }
    /* Forward envelope intact (typed body + session_id). */
    return ta_registry_post(g_target, env);
}

void ta_router_start(void) {
    (void)ta_registry_register(TA_CONTROLLER_NAME, ta_router_enqueue);
}
