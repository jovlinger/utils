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

static int set_route(const ta_event_t *ev) {
    size_t n;

    if (ev->payload_len == 0 || ev->payload_len >= TA_NAME_MAX) {
        fprintf(stderr, "ERROR: SetRoute bad payload\n");
        return -1;
    }
    n = (size_t)ev->payload_len;
    /* Payload is actor name bytes (may lack NUL; we add one). */
    memcpy(g_target, ev->payload, n);
    g_target[n] = '\0';
    if (g_target[0] == '\0') {
        return -1;
    }
    return 0;
}

int ta_router_enqueue(const ta_event_t *ev) {
    if (ev == NULL) {
        return -1;
    }
    if (ev->type == TA_EV_SET_ROUTE) {
        return set_route(ev);
    }
    if (g_target[0] == '\0') {
        fprintf(stderr, "ERROR: Controller has no route\n");
        return -1;
    }
    /* Forward envelope intact (reply_to / reply_type / session_id / payload). */
    return ta_registry_post(g_target, ev);
}

void ta_router_start(void) {
    (void)ta_registry_register(TA_CONTROLLER_NAME, ta_router_enqueue);
}
