#include "player_http.h"
#include "ta_net_backend.h"

#include <stdio.h>

#include "esp_log.h"

static const char *TAG = "ta_net";

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
    /* Arduino USB CDC often misses ESP_LOG; use both. */
    ESP_LOGI(TAG, "backend=player_http");
    printf("ta_net backend=player_http\n");
}

void ta_net_on_player_http_event(int ev) {
    /* Map PlayerHttpEvent enum values. */
    switch (ev) {
    case PLAYER_HTTP_EV_GETSTATE_OK:
        ta_net_backend_complete(1);
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
