#include "ta_http_actor.h"

#include "ta_net_http_event.h"
#include "ta_registry.h"

#include <string.h>

#ifdef SPINME_TA_DEVICE
/* Device-only: Arduino WiFiServer stopgap lives in ta_http_listen.cpp. */
extern void ta_http_listen_start_task(void);
#endif

void ta_http_reset(void) {
    /* Listen task is one-shot; no host-side listen state. */
}

int ta_http_enqueue(const ta_event_envelope_t *env) {
    if (env == NULL) {
        return -1;
    }
    if (env->event.type == TA_EV_LIST_EVENTS) {
        return ta_list_events_offer(
            env, "list_events,debug_status");
    }
    if (env->event.type == TA_EV_DEBUG_STATUS) {
        return ta_debug_status_reply(env, TA_HTTP_NAME, "listen");
    }
    return -1;
}

void ta_http_start(void) {
    (void)ta_registry_register(TA_HTTP_NAME, ta_http_enqueue);
}

void ta_http_wifi_up(void) {
#ifdef SPINME_TA_DEVICE
    ta_http_listen_start_task();
#else
    /* Host: inbound HTTP is out of process (tests drive handle_request). */
#endif
}
