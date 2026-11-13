/* Http TaskActor: inbound HTTP listen (device) + list_events.
 * WiFiServer / lwIP listen glue stays behind ta_http_wifi_up().
 */
#ifndef SPINME_TA_HTTP_ACTOR_H
#define SPINME_TA_HTTP_ACTOR_H

#include "ta_event.h"

#ifdef __cplusplus
extern "C" {
#endif

#define TA_HTTP_NAME "http"

void ta_http_reset(void);
void ta_http_start(void);
int ta_http_enqueue(const ta_event_envelope_t *env);

/* After WiFi is up: start the device listen task (no-op on host). */
void ta_http_wifi_up(void);

#ifdef __cplusplus
}
#endif
#endif
