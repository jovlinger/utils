#pragma once

/* Core B Volumio client. Non-blocking: start / select-poll / read / close.
 * The uimk2 worker must only call player_http_tick; it must never block on
 * DNS or HTTP. Boot may resolve WiFi + Volumio IP once.
 *
 * Volumio volume/toggle use GET:
 *   /api/v1/commands/?cmd=volume&volume=N
 *   /api/v1/commands/?cmd=toggle
 *
 * WIFI_SSID / WIFI_PASS come from the gitignored wifi header or build flags.
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

enum PlayerHttpEvent {
  PLAYER_HTTP_EV_NONE = 0,
  PLAYER_HTTP_EV_GETSTATE_OK,
  PLAYER_HTTP_EV_GETSTATE_FAIL,
  PLAYER_HTTP_EV_CMD_OK,
  PLAYER_HTTP_EV_CMD_FAIL,
  PLAYER_HTTP_EV_ALBUMART_OK,
  PLAYER_HTTP_EV_ALBUMART_FAIL
};

/* Connect WiFi and cache Volumio IP (blocking, boot only). */
void player_http_boot(void);

bool player_http_configured(void);

/* True while a socket op is in flight. */
bool player_http_busy(void);

/* Queue or start. Latest volume wins. getState coalesces while busy.
 * Returns false only when not configured. */
bool player_http_request_getstate(void);
bool player_http_request_toggle(void);
bool player_http_request_volume(int volume);
bool player_http_request_albumart(const char *albumart, size_t cap);

/* Zero-timeout select pump. At most one completion event per call. */
PlayerHttpEvent player_http_tick(void);

/* Valid after PLAYER_HTTP_EV_GETSTATE_OK until the next getState start. */
const PlayerSnapshot *player_http_snapshot(void);

/* After PLAYER_HTTP_EV_ALBUMART_OK: take ownership of the JPEG buffer
 * (caller free()s). */
bool player_http_take_albumart(uint8_t **buf_out, size_t *bytes_out,
                               uint32_t *ms_out);
