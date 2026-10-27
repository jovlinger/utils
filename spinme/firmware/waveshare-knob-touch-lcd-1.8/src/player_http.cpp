#include "player_http.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <esp_heap_caps.h>

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

static IPAddress gVolumioIp;
static bool gVolumioResolved = false;
static bool gMissingNoted = false;

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

static bool ensure_wifi(uint32_t timeout_ms) {
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
  /* US Eastern for the demo 24h clock. */
  setenv("TZ", "EST5EDT,M3.2.0/2,M11.1.0/2", 1);
  tzset();
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  return true;
}

static bool ensure_volumio_ip(void) {
  IPAddress ip;
  if (gVolumioResolved) {
    return true;
  }
  if (WiFi.status() != WL_CONNECTED) {
    return false;
  }
  /* hostByName can block a long time. Cache the address so later GETs
   * pass a literal IP and skip DNS. */
  if (!WiFi.hostByName(VOLUMIO_HOST, ip) || ip == IPAddress((uint32_t)0)) {
    Serial.printf("volumio dns fail %s\n", VOLUMIO_HOST);
    return false;
  }
  gVolumioIp = ip;
  gVolumioResolved = true;
  Serial.printf("volumio %s\n", gVolumioIp.toString().c_str());
  return true;
}

static bool volumio_get(const char *path, String *body, uint16_t timeout_ms) {
  HTTPClient http;
  int code;
  if (!player_http_configured()) {
    note_missing_ssid();
    return false;
  }
  if (!ensure_wifi(3000)) {
    return false;
  }
  if (!ensure_volumio_ip()) {
    return false;
  }
  if (!http.begin(gVolumioIp.toString(), (uint16_t)VOLUMIO_PORT, path)) {
    gVolumioResolved = false;
    Serial.println("player http begin fail");
    return false;
  }
  http.setConnectTimeout(1000);
  http.setTimeout(timeout_ms);
  code = http.GET();
  if (code == 200 && body != nullptr) {
    *body = http.getString();
  }
  http.end();
  if (code < 0) {
    gVolumioResolved = false;
    Serial.printf("player http fail %d\n", code);
    return false;
  }
  if (code != 200) {
    Serial.printf("player http %d\n", code);
    return false;
  }
  return true;
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

void player_http_boot(void) {
  if (!player_http_configured()) {
    note_missing_ssid();
    return;
  }
  (void)ensure_wifi(15000);
}

bool player_http_poll(PlayerSnapshot *out) {
  String body;
  const char *json;
  if (out == nullptr) {
    return false;
  }
  memset(out, 0, sizeof *out);
  out->volume = -1;
  if (!volumio_get("/api/v1/getState", &body, 2500)) {
    return false;
  }
  json = body.c_str();
  (void)json_string_field(json, "status", out->status, sizeof out->status);
  (void)json_string_field(json, "artist", out->artist, sizeof out->artist);
  (void)json_string_field(json, "album", out->album, sizeof out->album);
  (void)json_string_field(json, "title", out->title, sizeof out->title);
  (void)json_string_field(json, "albumart", out->albumart, sizeof out->albumart);
  out->have_status = out->status[0] != '\0';
  out->playing = strcmp(out->status, "play") == 0 ||
                 strcmp(out->status, "playing") == 0;
  out->volume = json_int_field(json, "volume", -1);
  if (out->volume < 0 || out->volume > 100) {
    out->volume = -1;
  }
  return true;
}

bool player_http_fetch_albumart(const char *albumart, size_t cap,
                                uint8_t **buf_out, size_t *bytes_out,
                                uint32_t *ms_out) {
  HTTPClient http;
  WiFiClient *stream;
  int code;
  size_t got = 0;
  size_t alloc = 0;
  uint32_t t0;
  uint8_t *buf = nullptr;
  int content_len;
  if (buf_out != nullptr) {
    *buf_out = nullptr;
  }
  if (bytes_out != nullptr) {
    *bytes_out = 0;
  }
  if (ms_out != nullptr) {
    *ms_out = 0;
  }
  if (albumart == nullptr || albumart[0] == '\0' || buf_out == nullptr) {
    return false;
  }
  if (!player_http_configured()) {
    note_missing_ssid();
    return false;
  }
  if (!ensure_wifi(3000)) {
    return false;
  }
  t0 = millis();
  if (strncmp(albumart, "http://", 7) == 0 ||
      strncmp(albumart, "https://", 8) == 0) {
    if (!http.begin(albumart)) {
      Serial.println("albumart begin fail");
      return false;
    }
  } else {
    const char *path = albumart;
    if (!ensure_volumio_ip()) {
      return false;
    }
    if (path[0] != '/') {
      Serial.println("albumart path not absolute");
      return false;
    }
    if (!http.begin(gVolumioIp.toString(), (uint16_t)VOLUMIO_PORT, path)) {
      gVolumioResolved = false;
      Serial.println("albumart begin fail");
      return false;
    }
  }
  http.setConnectTimeout(1000);
  http.setTimeout(4000);
  code = http.GET();
  if (code != 200) {
    http.end();
    if (code < 0) {
      gVolumioResolved = false;
    }
    Serial.printf("albumart http %d\n", code);
    return false;
  }
  content_len = http.getSize();
  if (content_len > 0) {
    alloc = (size_t)content_len;
  } else {
    alloc = 64u * 1024u;
  }
  if (cap != 0u && alloc > cap) {
    alloc = cap;
  }
  buf = static_cast<uint8_t *>(
      heap_caps_malloc(alloc, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (buf == nullptr) {
    buf = static_cast<uint8_t *>(malloc(alloc));
  }
  if (buf == nullptr) {
    http.end();
    return false;
  }
  stream = http.getStreamPtr();
  if (stream == nullptr) {
    free(buf);
    http.end();
    return false;
  }
  while (http.connected() && got < alloc) {
    size_t avail = stream->available();
    size_t n;
    size_t want;
    if (avail == 0u) {
      delay(1);
      if (!stream->connected() && stream->available() == 0) {
        break;
      }
      continue;
    }
    want = avail;
    if (want > alloc - got) {
      want = alloc - got;
    }
    n = stream->readBytes(buf + got, want);
    if (n == 0u) {
      break;
    }
    got += n;
  }
  http.end();
  if (got == 0u) {
    free(buf);
    return false;
  }
  *buf_out = buf;
  if (bytes_out != nullptr) {
    *bytes_out = got;
  }
  if (ms_out != nullptr) {
    *ms_out = millis() - t0;
  }
  return true;
}

bool player_http_toggle(void) {
  String body;
  return volumio_get("/api/v1/commands/?cmd=toggle", &body, 2500);
}

bool player_http_set_volume(int volume) {
  String body;
  char path[72];
  if (volume < 0) {
    volume = 0;
  }
  if (volume > 100) {
    volume = 100;
  }
  snprintf(path, sizeof path, "/api/v1/commands/?cmd=volume&volume=%d", volume);
  return volumio_get(path, &body, 800);
}
