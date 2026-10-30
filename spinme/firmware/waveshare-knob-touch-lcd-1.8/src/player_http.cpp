#include "player_http.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <Arduino.h>
#include <WiFi.h>
#include <esp_heap_caps.h>
#include <lwip/sockets.h>

#include "wifi_local.h"

#ifndef WIFI_SSID
#define WIFI_SSID SPINME_WIFI_SSID
#endif
#ifndef WIFI_PASS
#define WIFI_PASS SPINME_WIFI_PASS
#endif
#ifndef VOLUMIO_HOST
#define VOLUMIO_HOST "miniDSP-SHD.local"
#endif
#ifndef VOLUMIO_PORT
#define VOLUMIO_PORT 3000
#endif

#ifndef PLAYER_HTTP_BODY_MAX
#define PLAYER_HTTP_BODY_MAX (16u * 1024u)
#endif
#ifndef PLAYER_HTTP_HDR_MAX
#define PLAYER_HTTP_HDR_MAX 1024u
#endif
#ifndef PLAYER_HTTP_REQ_MAX
#define PLAYER_HTTP_REQ_MAX 384u
#endif

enum OpKind : uint8_t {
  OP_NONE = 0,
  OP_GETSTATE,
  OP_TOGGLE,
  OP_VOLUME,
  OP_ALBUMART
};

enum Phase : uint8_t {
  PH_IDLE = 0,
  PH_CONNECT,
  PH_SEND,
  PH_RECV_HDR,
  PH_RECV_BODY,
  PH_CLOSE
};

struct Pending {
  bool getstate;
  bool toggle;
  bool volume;
  int volume_val;
  bool albumart;
  char albumart_path[256];
  size_t albumart_cap;
};

static IPAddress gVolumioIp;
static bool gVolumioResolved = false;
static bool gMissingNoted = false;

static OpKind gKind = OP_NONE;
static Phase gPhase = PH_IDLE;
static int gSock = -1;
static char gReq[PLAYER_HTTP_REQ_MAX];
static size_t gReqLen = 0;
static size_t gReqSent = 0;
static char gHdr[PLAYER_HTTP_HDR_MAX];
static size_t gHdrLen = 0;
static int gHttpStatus = 0;
static int gContentLen = -1; /* -1 unknown */
static uint8_t *gBody = nullptr;
static size_t gBodyCap = 0;
static size_t gBodyGot = 0;
static uint32_t gOpStartMs = 0;
static uint32_t gAlbumartMs = 0;
static PlayerSnapshot gSnap;
static Pending gPend;
static char gAlbumartActive[256];
static size_t gAlbumartCap = 0;
static bool gHaveAlbumart = false;

static void note_missing_ssid(void) {
  if (gMissingNoted) {
    return;
  }
  gMissingNoted = true;
  Serial.println(
      "WIFI_SSID empty; set spinme/wifi.local.json or "
      "-DWIFI_SSID=... -DWIFI_PASS=...");
}

bool player_http_configured(void) { return WIFI_SSID[0] != '\0'; }

static void close_sock(void) {
  if (gSock >= 0) {
    lwip_close(gSock);
    gSock = -1;
  }
}

static void free_body(void) {
  if (gBody != nullptr) {
    free(gBody);
    gBody = nullptr;
  }
  gBodyCap = 0;
  gBodyGot = 0;
  gHaveAlbumart = false;
}

static void reset_op(void) {
  close_sock();
  gKind = OP_NONE;
  gPhase = PH_IDLE;
  gReqLen = 0;
  gReqSent = 0;
  gHdrLen = 0;
  gHttpStatus = 0;
  gContentLen = -1;
  if (!gHaveAlbumart) {
    free_body();
  }
}

static bool ensure_wifi_boot(uint32_t timeout_ms) {
  uint32_t start;
  if (!player_http_configured()) {
    note_missing_ssid();
    return false;
  }
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }
  Serial.printf("wifi connecting %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < timeout_ms) {
    delay(200);
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("wifi fail");
    return false;
  }
  gVolumioResolved = false;
  Serial.printf("wifi ok %s\n", WiFi.localIP().toString().c_str());
  setenv("TZ", "EST5EDT,M3.2.0/2,M11.1.0/2", 1);
  tzset();
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  return true;
}

static bool ensure_volumio_ip_boot(void) {
  IPAddress ip;
  if (gVolumioResolved) {
    return true;
  }
  if (WiFi.status() != WL_CONNECTED) {
    return false;
  }
  /* Boot-only DNS. Runtime never calls hostByName. */
  if (!WiFi.hostByName(VOLUMIO_HOST, ip) || ip == IPAddress((uint32_t)0)) {
    Serial.printf("volumio dns fail %s\n", VOLUMIO_HOST);
    return false;
  }
  gVolumioIp = ip;
  gVolumioResolved = true;
  Serial.printf("volumio %s\n", gVolumioIp.toString().c_str());
  return true;
}

static bool wifi_ready(void) {
  return player_http_configured() && WiFi.status() == WL_CONNECTED &&
         gVolumioResolved;
}

static const char *json_value(const char *body, const char *key) {
  char pat[40];
  int n;
  const char *p;
  n = snprintf(pat, sizeof pat, "\"%s\":", key);
  if (n <= 0 || (size_t)n >= sizeof pat) {
    return nullptr;
  }
  p = strstr(body, pat);
  if (p == nullptr) {
    return nullptr;
  }
  p += (size_t)n;
  while (*p == ' ' || *p == '\t') {
    p++;
  }
  return p;
}

static bool json_string_field(const char *body, const char *key, char *out,
                              size_t out_len) {
  const char *p;
  size_t n = 0;
  if (out_len == 0) {
    return false;
  }
  out[0] = '\0';
  p = json_value(body, key);
  if (p == nullptr || *p != '"') {
    return false;
  }
  p++;
  while (*p != '\0' && *p != '"' && n + 1 < out_len) {
    if (*p == '\\' && p[1] != '\0') {
      p++;
    }
    out[n++] = *p++;
  }
  out[n] = '\0';
  return true;
}

static int json_int_field(const char *body, const char *key, int fallback) {
  const char *p;
  bool neg = false;
  int value = 0;
  p = json_value(body, key);
  if (p == nullptr) {
    return fallback;
  }
  if (*p == '-') {
    neg = true;
    p++;
  }
  if (*p < '0' || *p > '9') {
    return fallback;
  }
  while (*p >= '0' && *p <= '9') {
    value = value * 10 + (*p - '0');
    p++;
  }
  return neg ? -value : value;
}

static void parse_getstate(const char *json) {
  memset(&gSnap, 0, sizeof gSnap);
  gSnap.volume = -1;
  (void)json_string_field(json, "status", gSnap.status, sizeof gSnap.status);
  (void)json_string_field(json, "artist", gSnap.artist, sizeof gSnap.artist);
  (void)json_string_field(json, "album", gSnap.album, sizeof gSnap.album);
  (void)json_string_field(json, "title", gSnap.title, sizeof gSnap.title);
  (void)json_string_field(json, "albumart", gSnap.albumart,
                          sizeof gSnap.albumart);
  gSnap.have_status = gSnap.status[0] != '\0';
  gSnap.playing = strcmp(gSnap.status, "play") == 0 ||
                  strcmp(gSnap.status, "playing") == 0;
  gSnap.volume = json_int_field(json, "volume", -1);
  if (gSnap.volume < 0 || gSnap.volume > 100) {
    gSnap.volume = -1;
  }
}

static bool build_request(OpKind kind) {
  const char *path = "/";
  char vol_path[72];
  int n;
  if (kind == OP_GETSTATE) {
    path = "/api/v1/getState";
  } else if (kind == OP_TOGGLE) {
    path = "/api/v1/commands/?cmd=toggle";
  } else if (kind == OP_VOLUME) {
    int v = gPend.volume_val;
    if (v < 0) {
      v = 0;
    }
    if (v > 100) {
      v = 100;
    }
    snprintf(vol_path, sizeof vol_path,
             "/api/v1/commands/?cmd=volume&volume=%d", v);
    path = vol_path;
  } else if (kind == OP_ALBUMART) {
    path = gAlbumartActive;
    if (path[0] == '\0') {
      return false;
    }
    if (strncmp(path, "http://", 7) == 0 || strncmp(path, "https://", 8) == 0) {
      Serial.println("albumart absolute URL not supported in nb client");
      return false;
    }
    if (path[0] != '/') {
      Serial.println("albumart path not absolute");
      return false;
    }
  } else {
    return false;
  }
  n = snprintf(gReq, sizeof gReq,
               "GET %s HTTP/1.0\r\nHost: %s\r\nConnection: close\r\n\r\n", path,
               VOLUMIO_HOST);
  if (n <= 0 || (size_t)n >= sizeof gReq) {
    return false;
  }
  gReqLen = (size_t)n;
  gReqSent = 0;
  return true;
}

static bool alloc_body(size_t cap) {
  free_body();
  if (cap == 0u) {
    cap = 64u * 1024u;
  }
  gBody = static_cast<uint8_t *>(
      heap_caps_malloc(cap, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (gBody == nullptr) {
    gBody = static_cast<uint8_t *>(malloc(cap));
  }
  if (gBody == nullptr) {
    return false;
  }
  gBodyCap = cap;
  gBodyGot = 0;
  return true;
}

static bool start_connect(OpKind kind) {
  struct sockaddr_in addr;
  int flags;
  int rc;
  if (!wifi_ready()) {
    return false;
  }
  if (!build_request(kind)) {
    return false;
  }
  if (kind == OP_ALBUMART) {
    size_t cap = gAlbumartCap != 0u ? gAlbumartCap : 512u * 1024u;
    if (!alloc_body(cap)) {
      return false;
    }
  } else if (kind == OP_GETSTATE) {
    if (!alloc_body(PLAYER_HTTP_BODY_MAX)) {
      return false;
    }
  } else {
    free_body();
    if (!alloc_body(PLAYER_HTTP_BODY_MAX)) {
      return false;
    }
  }
  gSock = lwip_socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  if (gSock < 0) {
    free_body();
    return false;
  }
  flags = lwip_fcntl(gSock, F_GETFL, 0);
  if (flags >= 0) {
    (void)lwip_fcntl(gSock, F_SETFL, flags | O_NONBLOCK);
  }
  memset(&addr, 0, sizeof addr);
  addr.sin_family = AF_INET;
  addr.sin_port = htons((uint16_t)VOLUMIO_PORT);
  addr.sin_addr.s_addr = static_cast<uint32_t>(gVolumioIp);
  rc = lwip_connect(gSock, (struct sockaddr *)&addr, sizeof addr);
  if (rc == 0) {
    gPhase = PH_SEND;
  } else if (errno == EINPROGRESS) {
    gPhase = PH_CONNECT;
  } else {
    Serial.printf("player connect errno %d\n", errno);
    close_sock();
    free_body();
    return false;
  }
  gKind = kind;
  gHdrLen = 0;
  gHttpStatus = 0;
  gContentLen = -1;
  gOpStartMs = millis();
  gHaveAlbumart = false;
  return true;
}

static void kick_pending(void) {
  OpKind next = OP_NONE;
  if (gPhase != PH_IDLE || gKind != OP_NONE) {
    return;
  }
  if (!wifi_ready()) {
    return;
  }
  /* Prefer commands, then getState, then albumart. */
  if (gPend.toggle) {
    gPend.toggle = false;
    next = OP_TOGGLE;
  } else if (gPend.volume) {
    gPend.volume = false;
    next = OP_VOLUME;
  } else if (gPend.getstate) {
    gPend.getstate = false;
    next = OP_GETSTATE;
  } else if (gPend.albumart) {
    gPend.albumart = false;
    strncpy(gAlbumartActive, gPend.albumart_path, sizeof gAlbumartActive - 1u);
    gAlbumartActive[sizeof gAlbumartActive - 1u] = '\0';
    gAlbumartCap = gPend.albumart_cap;
    next = OP_ALBUMART;
  }
  if (next == OP_NONE) {
    return;
  }
  if (!start_connect(next)) {
    Serial.printf("player start fail kind=%u\n", (unsigned)next);
  }
}

static bool parse_status_line(void) {
  /* HTTP/1.x NNN */
  const char *p = gHdr;
  if (strncmp(p, "HTTP/", 5) != 0) {
    return false;
  }
  p = strchr(p, ' ');
  if (p == nullptr) {
    return false;
  }
  p++;
  gHttpStatus = atoi(p);
  return gHttpStatus > 0;
}

static void parse_headers_done(void) {
  char *cl;
  (void)parse_status_line();
  cl = strstr(gHdr, "Content-Length:");
  if (cl == nullptr) {
    cl = strstr(gHdr, "content-length:");
  }
  if (cl != nullptr) {
    cl = strchr(cl, ':');
    if (cl != nullptr) {
      gContentLen = atoi(cl + 1);
    }
  }
  if (gKind == OP_ALBUMART && gContentLen > 0) {
    size_t want = (size_t)gContentLen;
    if (gAlbumartCap != 0u && want > gAlbumartCap) {
      want = gAlbumartCap;
    }
    if (want > gBodyCap) {
      uint8_t *nb = static_cast<uint8_t *>(
          heap_caps_malloc(want, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
      if (nb == nullptr) {
        nb = static_cast<uint8_t *>(malloc(want));
      }
      if (nb != nullptr) {
        memcpy(nb, gBody, gBodyGot);
        free(gBody);
        gBody = nb;
        gBodyCap = want;
      }
    }
  }
}

static bool hdr_complete(void) {
  char *sp = strstr(gHdr, "\r\n\r\n");
  size_t hdr_bytes;
  size_t extra;
  if (sp == nullptr) {
    return false;
  }
  hdr_bytes = (size_t)(sp - gHdr) + 4u;
  parse_headers_done();
  extra = gHdrLen - hdr_bytes;
  if (extra > 0u && gBody != nullptr && extra <= gBodyCap) {
    memcpy(gBody, gHdr + hdr_bytes, extra);
    gBodyGot = extra;
  }
  gHdrLen = hdr_bytes;
  return true;
}

static PlayerHttpEvent finish_ok(void) {
  PlayerHttpEvent ev = PLAYER_HTTP_EV_CMD_OK;
  OpKind kind = gKind;
  if (kind == OP_GETSTATE) {
    if (gHttpStatus == 200 && gBody != nullptr && gBodyGot > 0u) {
      if (gBodyGot >= gBodyCap) {
        gBody[gBodyCap - 1u] = '\0';
      } else {
        gBody[gBodyGot] = '\0';
      }
      parse_getstate(reinterpret_cast<char *>(gBody));
      ev = PLAYER_HTTP_EV_GETSTATE_OK;
    } else {
      ev = PLAYER_HTTP_EV_GETSTATE_FAIL;
    }
    free_body();
  } else if (kind == OP_ALBUMART) {
    if (gHttpStatus == 200 && gBodyGot > 0u) {
      gHaveAlbumart = true;
      gAlbumartMs = millis() - gOpStartMs;
      ev = PLAYER_HTTP_EV_ALBUMART_OK;
    } else {
      free_body();
      ev = PLAYER_HTTP_EV_ALBUMART_FAIL;
    }
  } else {
    if (gHttpStatus != 200) {
      ev = PLAYER_HTTP_EV_CMD_FAIL;
    }
    free_body();
  }
  close_sock();
  gKind = OP_NONE;
  gPhase = PH_IDLE;
  return ev;
}

static PlayerHttpEvent finish_fail(void) {
  PlayerHttpEvent ev;
  OpKind kind = gKind;
  if (kind == OP_GETSTATE) {
    ev = PLAYER_HTTP_EV_GETSTATE_FAIL;
  } else if (kind == OP_ALBUMART) {
    ev = PLAYER_HTTP_EV_ALBUMART_FAIL;
  } else {
    ev = PLAYER_HTTP_EV_CMD_FAIL;
  }
  /* Keep the boot-cached IP. Runtime never calls hostByName; clearing
   * the cache would permanently stall player IO until reboot. */
  free_body();
  close_sock();
  gKind = OP_NONE;
  gPhase = PH_IDLE;
  Serial.printf("player fail kind=%u status=%d\n", (unsigned)kind, gHttpStatus);
  return ev;
}

static int select_sock(bool want_read, bool want_write) {
  fd_set rfds;
  fd_set wfds;
  struct timeval tv;
  int nfds;
  if (gSock < 0) {
    return -1;
  }
  FD_ZERO(&rfds);
  FD_ZERO(&wfds);
  if (want_read) {
    FD_SET(gSock, &rfds);
  }
  if (want_write) {
    FD_SET(gSock, &wfds);
  }
  tv.tv_sec = 0;
  tv.tv_usec = 0;
  nfds = lwip_select(gSock + 1, want_read ? &rfds : nullptr,
                     want_write ? &wfds : nullptr, nullptr, &tv);
  if (nfds < 0) {
    return -1;
  }
  if (nfds == 0) {
    return 0;
  }
  if (want_read && FD_ISSET(gSock, &rfds)) {
    return 1;
  }
  if (want_write && FD_ISSET(gSock, &wfds)) {
    return 1;
  }
  return 0;
}

void player_http_boot(void) {
  memset(&gPend, 0, sizeof gPend);
  memset(&gSnap, 0, sizeof gSnap);
  gSnap.volume = -1;
  if (!player_http_configured()) {
    note_missing_ssid();
    return;
  }
  if (!ensure_wifi_boot(15000)) {
    return;
  }
  (void)ensure_volumio_ip_boot();
}

bool player_http_busy(void) { return gPhase != PH_IDLE || gKind != OP_NONE; }

bool player_http_request_getstate(void) {
  if (!player_http_configured()) {
    note_missing_ssid();
    return false;
  }
  gPend.getstate = true;
  kick_pending();
  return true;
}

bool player_http_request_toggle(void) {
  if (!player_http_configured()) {
    note_missing_ssid();
    return false;
  }
  gPend.toggle = true;
  kick_pending();
  return true;
}

bool player_http_request_volume(int volume) {
  if (!player_http_configured()) {
    note_missing_ssid();
    return false;
  }
  gPend.volume = true;
  gPend.volume_val = volume;
  kick_pending();
  return true;
}

bool player_http_request_albumart(const char *albumart, size_t cap) {
  if (!player_http_configured()) {
    note_missing_ssid();
    return false;
  }
  if (albumart == nullptr || albumart[0] == '\0') {
    return false;
  }
  strncpy(gPend.albumart_path, albumart, sizeof gPend.albumart_path - 1u);
  gPend.albumart_path[sizeof gPend.albumart_path - 1u] = '\0';
  gPend.albumart_cap = cap;
  gPend.albumart = true;
  kick_pending();
  return true;
}

const PlayerSnapshot *player_http_snapshot(void) { return &gSnap; }

bool player_http_take_albumart(uint8_t **buf_out, size_t *bytes_out,
                               uint32_t *ms_out) {
  if (!gHaveAlbumart || gBody == nullptr || gBodyGot == 0u) {
    return false;
  }
  if (buf_out != nullptr) {
    *buf_out = gBody;
  }
  if (bytes_out != nullptr) {
    *bytes_out = gBodyGot;
  }
  if (ms_out != nullptr) {
    *ms_out = gAlbumartMs;
  }
  gBody = nullptr;
  gBodyCap = 0;
  gBodyGot = 0;
  gHaveAlbumart = false;
  return true;
}

PlayerHttpEvent player_http_tick(void) {
  PlayerHttpEvent ev = PLAYER_HTTP_EV_NONE;
  int ready;
  int so_err = 0;
  socklen_t so_len = sizeof so_err;
  ssize_t n;

  if (gPhase == PH_IDLE) {
    kick_pending();
    return PLAYER_HTTP_EV_NONE;
  }

  /* Overall cap so a half-open peer cannot pin the phase forever. */
  if (millis() - gOpStartMs > 8000u) {
    Serial.println("player op timeout");
    return finish_fail();
  }

  switch (gPhase) {
  case PH_CONNECT:
    ready = select_sock(false, true);
    if (ready < 0) {
      return finish_fail();
    }
    if (ready == 0) {
      return PLAYER_HTTP_EV_NONE;
    }
    if (lwip_getsockopt(gSock, SOL_SOCKET, SO_ERROR, &so_err, &so_len) < 0 ||
        so_err != 0) {
      Serial.printf("player connect so_err %d\n", so_err);
      return finish_fail();
    }
    gPhase = PH_SEND;
    /* fall through */
  case PH_SEND:
    while (gReqSent < gReqLen) {
      ready = select_sock(false, true);
      if (ready < 0) {
        return finish_fail();
      }
      if (ready == 0) {
        return PLAYER_HTTP_EV_NONE;
      }
      n = lwip_send(gSock, gReq + gReqSent, gReqLen - gReqSent, 0);
      if (n < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
          return PLAYER_HTTP_EV_NONE;
        }
        return finish_fail();
      }
      gReqSent += (size_t)n;
    }
    gPhase = PH_RECV_HDR;
    /* fall through */
  case PH_RECV_HDR:
    for (;;) {
      ready = select_sock(true, false);
      if (ready < 0) {
        return finish_fail();
      }
      if (ready == 0) {
        return PLAYER_HTTP_EV_NONE;
      }
      if (gHdrLen + 1u >= sizeof gHdr) {
        return finish_fail();
      }
      n = lwip_recv(gSock, gHdr + gHdrLen, sizeof gHdr - 1u - gHdrLen, 0);
      if (n < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
          return PLAYER_HTTP_EV_NONE;
        }
        return finish_fail();
      }
      if (n == 0) {
        return finish_fail();
      }
      gHdrLen += (size_t)n;
      gHdr[gHdrLen] = '\0';
      if (hdr_complete()) {
        if (gHttpStatus != 200 && gKind != OP_ALBUMART) {
          /* Still drain via close; treat as fail after body or now. */
        }
        gPhase = PH_RECV_BODY;
        break;
      }
    }
    /* fall through */
  case PH_RECV_BODY:
    for (;;) {
      size_t room;
      if (gContentLen >= 0 && (int)gBodyGot >= gContentLen) {
        return finish_ok();
      }
      if (gBody == nullptr) {
        return finish_fail();
      }
      room = gBodyCap - gBodyGot;
      if (room == 0u) {
        return finish_ok();
      }
      ready = select_sock(true, false);
      if (ready < 0) {
        return finish_fail();
      }
      if (ready == 0) {
        return PLAYER_HTTP_EV_NONE;
      }
      n = lwip_recv(gSock, gBody + gBodyGot, room, 0);
      if (n < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
          return PLAYER_HTTP_EV_NONE;
        }
        return finish_fail();
      }
      if (n == 0) {
        /* peer closed */
        return finish_ok();
      }
      gBodyGot += (size_t)n;
    }
  case PH_CLOSE:
  case PH_IDLE:
  default:
    reset_op();
    break;
  }
  (void)ev;
  return PLAYER_HTTP_EV_NONE;
}
