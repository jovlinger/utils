#include "player_http.h"
#include "ta_draw_events.h"
#include "ta_draw_glass.h"
#include "ta_net_backend.h"
#include "ta_net_events.h"
#include "ta_registry.h"

#include <stdio.h>
#include <string.h>

#include "esp_log.h"

static const char *TAG = "ta_net";

/* Last artwork path handed to Net; a change requests a new fetch. */
static char g_last_albumart[256];

static int req_poll(void) {
    return player_http_request_getstate() ? 0 : -1;
}

static int req_toggle(void) {
    return player_http_request_toggle() ? 0 : -1;
}

static int req_volume(int volume) {
    return player_http_request_volume(volume) ? 0 : -1;
}

static int req_albumart(const char *path, size_t cap) {
    return player_http_request_albumart(path, cap) ? 0 : -1;
}

static const ta_net_backend_t g_player_backend = {
    req_poll, req_toggle, req_volume, req_albumart};

void ta_net_bind_player_http(void) {
    ta_net_set_backend(&g_player_backend);
    g_last_albumart[0] = '\0';
    /* Arduino USB CDC often misses ESP_LOG; use both. */
    ESP_LOGI(TAG, "backend=player_http");
    printf("ta_net backend=player_http\n");
}

/* Volumio getState -> POLL_DONE status payload + Draw text fields. Net is
 * the dialect edge: it knows the player's status shape, Draw only sees
 * typed events. Artwork path changes request NET_ALBUMART (fetch only; the
 * decode glue listens for ALBUMART_OK). */
static void on_getstate_ok(void) {
    const PlayerSnapshot *snap = player_http_snapshot();
    uint8_t status[TA_NET_STATUS_LEN];

    status[TA_NET_STATUS_VOLUME] = TA_NET_STATUS_UNKNOWN;
    status[TA_NET_STATUS_PLAYING] = TA_NET_STATUS_UNKNOWN;
    if (snap != NULL) {
        if (snap->volume >= 0 && snap->volume <= 100) {
            status[TA_NET_STATUS_VOLUME] = (uint8_t)snap->volume;
        }
        if (snap->have_status) {
            status[TA_NET_STATUS_PLAYING] = snap->playing ? 1u : 0u;
        }
        (void)ta_draw_post_text(TA_DRAW_TEXT_ARTIST, snap->artist, 1,
                                TA_NET_NAME);
        (void)ta_draw_post_text(TA_DRAW_TEXT_ALBUM, snap->album, 1,
                                TA_NET_NAME);
        (void)ta_draw_post_text(TA_DRAW_TEXT_TITLE, snap->title, 1,
                                TA_NET_NAME);
        printf("player poll %s vol %d\n",
               snap->status[0] != '\0' ? snap->status : "?", snap->volume);
        if (snap->albumart[0] != '\0' &&
            strncmp(snap->albumart, g_last_albumart,
                    sizeof g_last_albumart) != 0) {
            ta_event_t ev;
            size_t n = strlen(snap->albumart);

            if (n > TA_PAYLOAD_MAX) {
                n = TA_PAYLOAD_MAX;
            }
            strncpy(g_last_albumart, snap->albumart,
                    sizeof g_last_albumart - 1u);
            g_last_albumart[sizeof g_last_albumart - 1u] = '\0';
            ta_event_clear(&ev);
            ev.type = TA_EV_NET_ALBUMART;
            ev.session_id = 1;
            (void)ta_event_set_src(&ev, TA_NET_NAME);
            (void)ta_event_set_payload(&ev, snap->albumart, n);
            (void)ta_registry_post(TA_NET_NAME, &ev);
        }
    }
    ta_net_backend_complete_ex(1, status, sizeof status);
}

void ta_net_on_player_http_event(int ev) {
    /* Map PlayerHttpEvent enum values. */
    switch (ev) {
    case PLAYER_HTTP_EV_GETSTATE_OK:
        on_getstate_ok();
        break;
    case PLAYER_HTTP_EV_GETSTATE_FAIL:
        ta_net_backend_complete(2);
        break;
    case PLAYER_HTTP_EV_CMD_OK:
        ta_net_backend_complete(3);
        break;
    case PLAYER_HTTP_EV_CMD_FAIL:
        ta_net_backend_complete(4);
        break;
    case PLAYER_HTTP_EV_ALBUMART_OK:
        ta_net_backend_complete(5);
        break;
    case PLAYER_HTTP_EV_ALBUMART_FAIL:
        ta_net_backend_complete(6);
        break;
    default:
        break;
    }
}
