/* Net: HTTP POST /event/<actor>/<event> ingress + mDNS advertise stub. */
#ifndef SPINME_TA_NET_HTTP_EVENT_H
#define SPINME_TA_NET_HTTP_EVENT_H

#include "ta_event.h"

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Async event -> sync HTTP: incomplete / no reply within this -> HTTP 201. */
#define TA_TIMEOUT_SHORT_MS 2000u
#define TA_NET_HTTP_TIMEOUT_MS TA_TIMEOUT_SHORT_MS
#define TA_NET_HTTP_RESP_BODY_MAX 256
#define TA_NET_HTTP_BLOB_MAX (256u * 1024u)

typedef struct {
    int http_status;
    char body[TA_NET_HTTP_RESP_BODY_MAX];
    size_t body_len;
    /* Optional large payload (e.g. get_debug). Owned by caller of handle;
     * module frees any prior blob on the next offer/reset/fill. */
    uint8_t *blob;
    size_t blob_len;
} ta_net_http_response_t;

/* Wait for TA_EV_NET_HTTP_REPLY with matching session_id. 0=got, -1=timeout. */
typedef int (*ta_net_http_wait_fn)(ta_session_id_t session_id,
                                   ta_event_envelope_t *out,
                                   uint32_t timeout_ms);

void ta_net_http_reset(void);
void ta_net_http_set_wait(ta_net_http_wait_fn fn);
/* Actor handlers call this to satisfy an in-flight HTTP wait (host/sync). */
void ta_net_http_offer_reply(const ta_event_envelope_t *env);
/* Large body (copies bytes). Prefer over NetHttpReply when > 64 B. */
void ta_net_http_offer_blob(ta_session_id_t session_id, unsigned http_status,
                            const void *bytes, size_t n);

/*
 * Handle one HTTP/1.x request buffer. Fills *out.
 * POST /event/<actor>/<eventname>[?query] with optional form body.
 * Query and body are both parsed as x-www-form-urlencoded; body keys win.
 */
int ta_net_http_handle_request(const uint8_t *req, size_t len,
                               ta_net_http_response_t *out);

/* mDNS advertise (Scheduler-timed). Host counts broadcasts. */
void ta_net_mdns_reset(void);
void ta_net_mdns_set_name(const char *name);
int ta_net_mdns_advertise(void); /* 0 ok */
unsigned ta_net_mdns_advertise_count(void);

#ifdef __cplusplus
}
#endif
#endif
