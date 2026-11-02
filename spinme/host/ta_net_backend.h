/* Net -> player wire seam. NULL backend = host immediate DONE replies. */
#ifndef SPINME_TA_NET_BACKEND_H
#define SPINME_TA_NET_BACKEND_H

#include "ta_event.h"

#include <stddef.h>

/* NET_SET payload[0]: op. */

#ifdef __cplusplus
extern "C" {
#endif

enum {
    TA_NET_SET_OP_VOLUME = 0,
    TA_NET_SET_OP_TOGGLE = 1
};

typedef struct ta_net_backend {
    /* Return 0 if accepted/queued, -1 if rejected (not configured). */
    int (*request_poll)(void);
    int (*request_toggle)(void);
    int (*request_volume)(int volume);
    int (*request_albumart)(const char *path, size_t cap);
} ta_net_backend_t;

void ta_net_set_backend(const ta_net_backend_t *backend);

/*
 * Device: call when player_http_tick returns a completion.
 * kind: 1=poll ok, 2=poll fail, 3=cmd ok, 4=cmd fail, 5=art ok, 6=art fail.
 */
void ta_net_backend_complete(int kind);


#ifdef __cplusplus
}
#endif
#endif
