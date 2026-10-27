#pragma once

/* Core B Volumio client. GET /api/v1/getState and the commands API.
 * Volumio sets volume with GET, not POST:
 * /api/v1/commands/?cmd=volume&volume=N
 * Toggle is /api/v1/commands/?cmd=toggle.
 *
 * WIFI_SSID / WIFI_PASS come from the gitignored wifi header or from
 * build flags. An empty SSID still links; calls return false.
 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

struct PlayerSnapshot {
  int volume; /* 0..100, or -1 when the body had no volume */
  bool playing;
  bool have_status;
  char status[16];
  char artist[96];
  char album[96];
  char title[96];
  /* Relative (/albumart?...) or absolute http(s) URL from getState. */
  char albumart[256];
};

/* Connect when WIFI_SSID is set. Logs a clear line when it is empty. */
void player_http_boot(void);

bool player_http_configured(void);

/* GET getState. False when WiFi or HTTP fails. */
bool player_http_poll(PlayerSnapshot *out);

/* PoC: GET albumart into a heap buffer (PSRAM preferred). Caller free()s
 * *buf_out. Cap stops a runaway body. False on HTTP/WiFi failure. */
bool player_http_fetch_albumart(const char *albumart, size_t cap,
                                uint8_t **buf_out, size_t *bytes_out,
                                uint32_t *ms_out);

/* GET commands/?cmd=toggle. Does not refresh state. */
bool player_http_toggle(void);

/* GET commands/?cmd=volume&volume=N. N is clamped to 0..100. */
bool player_http_set_volume(int volume);
