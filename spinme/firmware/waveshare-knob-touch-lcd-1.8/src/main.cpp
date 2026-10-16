#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <driver/gpio.h>
#include <esp_timer.h>
#include <stdio.h>
#include <string.h>

#include "board_pins.h"
#include "encoder_decode.h"
#include "glyph_file.h"
#include "layout_box.h"
#include "panel_init.h"
#include "panel_io.h"
#include "wifi_local.h"

#ifndef VOLUMIO_HOST
#define VOLUMIO_HOST "miniDSP-SHD.local"
#endif

static const uint16_t kVolumioPort = 3000;
static const uint32_t kIdleSleepMs = 30000;
static const uint16_t kYellow = 0xFFE0;
static const uint16_t kWhite = 0xFFFF;

static bool gDisplayOk = false;
static bool gAwake = true;
static uint32_t gLastActivityMs = 0;
static char gStatus[24] = "boot";
static char gArtist[48] = "";
static char gTitle[48] = VOLUMIO_HOST;
static char gActivity[32] = "";
static int gVolume = -1;
/* Steps not yet acknowledged by Volumio. The glass shows gVolume + gUnsent
 * immediately. HTTP goes out at about 2 Hz as one absolute volume. */
static int gUnsent = 0;
static int gTakenRot = 0;
static uint32_t gLastVolSendMs = 0;
static uint32_t gVolArmMs = 0;
static const uint32_t kVolSendGapMs = 500;
static const uint32_t kVolGatherMs = 100;
/* First pin to change after the chatter lock is the click.
 * GPIO8 = +1, GPIO7 = -1. The same pin can repeat during a fast spin. */
static volatile int gRotation = 0;
static volatile uint8_t gEncLast = 0;
static volatile uint8_t gClickPin = 0;
static volatile uint32_t gClickLockUs = 0;
static volatile uint32_t gClickHighUs = 0;
static int gDrawnRotation = 0;

struct EncEdge {
  uint32_t us;
  uint8_t prev;
  uint8_t cur;
  int8_t step;
  int rot;
};

static const int kEncLogCap = 128;
static EncEdge DRAM_ATTR gEncLog[kEncLogCap];
static volatile uint16_t gEncLogW = 0;
static volatile uint16_t gEncLogR = 0;
static volatile uint16_t gEncDrop = 0;
static uint16_t gTouchCount = 0;
static uint32_t gLastPollMs = 0;
static uint32_t gLastInputMs = 0;
static bool gUiDirty = false;
static bool gPlayerRefresh = false;
/* Paint and the volume write wait this long after the last knob or
 * touch edge. The encoder's other-pin lock stays 200 ms. */
static const uint32_t kUiQuietMs = 100;
static bool gStatusBtnValid = false;
static int gStatusBtnX = 0;
static int gStatusBtnY = 0;
static int gStatusBtnW = 0;
static int gStatusBtnH = 0;
static char gPaintedLabel[8] = "";
static char gPaintedLine[6][48];
static int gPaintedCount = -1;

static void copy_text(char *dest, size_t dest_len, const char *src) {
  size_t i = 0;
  if (src == nullptr) {
    dest[0] = '\0';
    return;
  }
  while (src[i] != '\0' && i + 1 < dest_len) {
    dest[i] = src[i];
    i++;
  }
  dest[i] = '\0';
}

/* Round glass over a square 360 framebuffer. Keep this in step with
 * screenmock/layout.py. A line is l2r(glyphs and shims, bot). Lines are
 * t2b(..., left), with a line shim inside a section and a section shim
 * between sections. The union center sits on the glass center.
 */
static const int kTextSize = 1;
static const int kLineCount = 6;
static const int kLineChars = 48;
static const int kPartCap = kLineCount * 2;
static const int kLineSection[kLineCount] = {0, 0, 1, 1, 2, 2};
static const int kTransportY = 24;
static const int kTransportPadX = 12;
static const int kTransportPadY = 6;

static bool box_inside_circle(int x, int y, int w, int h) {
  if (w <= 0 || h <= 0) {
    return true;
  }
  const int cx = LCD_WIDTH / 2;
  const int cy = LCD_HEIGHT / 2;
  const int r = LCD_WIDTH / 2;
  const int xs[2] = {x, x + w - 1};
  const int ys[2] = {y, y + h - 1};
  for (int ix = 0; ix < 2; ++ix) {
    for (int iy = 0; iy < 2; ++iy) {
      const int dx = xs[ix] - cx;
      const int dy = ys[iy] - cy;
      if (dx * dx + dy * dy > r * r) {
        return false;
      }
    }
  }
  return true;
}

static void drop_line(char lines[][kLineChars], uint16_t *colors, int *sections,
                      int count, int index) {
  for (int j = index; j + 1 < count; ++j) {
    copy_text(lines[j], kLineChars, lines[j + 1]);
    colors[j] = colors[j + 1];
    sections[j] = sections[j + 1];
  }
}

static void compose_block(char lines[][kLineChars], const int *sections,
                          int count, LayAt *placed, LayUnion *block,
                          int *slot) {
  LayBox parts[kPartCap];
  int n = 0;
  int prev = -1;
  for (int i = 0; i < count; ++i) {
    slot[i] = -1;
    int width = 0;
    int height = 0;
    if (!glyph_line_size(lines[i], &width, &height)) {
      continue;
    }
    if (n > 0 && n + 1 < kPartCap) {
      parts[n++] = (sections[i] != prev) ? glyph_section_vshim() : glyph_line_vshim();
    }
    if (n >= kPartCap) {
      continue;
    }
    parts[n].w = width;
    parts[n].h = height;
    slot[i] = n;
    n++;
    prev = sections[i];
  }
  lay_t2b(parts, n, HAlign_left, placed, block);
}

/* Drop trailing characters until every left-aligned line is in the circle.
 * The block stays vertically centered. */
static int fit_block(char lines[][kLineChars], uint16_t *colors, int *sections,
                     int count) {
  while (count > 0) {
    LayAt placed[kPartCap];
    int slot[kLineCount];
    LayUnion block;
    compose_block(lines, sections, count, placed, &block, slot);
    const int ax = LCD_WIDTH / 2;
    const int ay = LCD_HEIGHT / 2;
    int worst = -1;
    int worst_w = -1;
    for (int i = 0; i < count; ++i) {
      if (slot[i] < 0) {
        worst = i;
        worst_w = 100000;
        break;
      }
      const LayAt *at = &placed[slot[i]];
      const int left = ax + lay_left(at);
      const int top = ay + lay_top(at);
      if (!box_inside_circle(left, top, at->w, at->h) && at->w > worst_w) {
        worst = i;
        worst_w = at->w;
      }
    }
    if (worst < 0) {
      return count;
    }
    const size_t n = strlen(lines[worst]);
    if (n == 0 || slot[worst] < 0) {
      drop_line(lines, colors, sections, count, worst);
      count--;
      continue;
    }
    lines[worst][n - 1] = '\0';
    if (lines[worst][0] == '\0') {
      drop_line(lines, colors, sections, count, worst);
      count--;
    }
  }
  return count;
}

static const char *transport_label(void) {
  if (strcmp(gStatus, "play") == 0) {
    return "stop";
  }
  return "play";
}

static bool status_button_hit(uint16_t x, uint16_t y) {
  if (!gStatusBtnValid) {
    return false;
  }
  return (int)x >= gStatusBtnX && (int)y >= gStatusBtnY &&
         (int)x < gStatusBtnX + gStatusBtnW &&
         (int)y < gStatusBtnY + gStatusBtnH;
}

/* White rectangle near the top of the glass. Tap sends Volumio toggle.
 * The rect is the wider of "play" and "stop", so it does not move. */
static void place_transport_button(void) {
  const int play_w = panel_text_width("play");
  const int stop_w = panel_text_width("stop");
  const int tw = play_w > stop_w ? play_w : stop_w;
  const int bw = tw + kTransportPadX * 2;
  const int bh = glyph_body_h() + kTransportPadY * 2;
  gStatusBtnX = (LCD_WIDTH - bw) / 2;
  gStatusBtnY = kTransportY;
  gStatusBtnW = bw;
  gStatusBtnH = bh;
  gStatusBtnValid = true;
}

static int optimistic_volume(void) {
  if (gVolume < 0) {
    return gVolume;
  }
  int volume = gVolume + gUnsent;
  if (volume < 0) {
    return 0;
  }
  if (volume > 100) {
    return 100;
  }
  return volume;
}

static void paint_transport_button(void) {
  const char *label = transport_label();
  panel_fill_rect(gStatusBtnX, gStatusBtnY, gStatusBtnW, gStatusBtnH, kWhite);
  const int tw = panel_text_width(label);
  const int inner = gStatusBtnW - kTransportPadX * 2;
  const int x = gStatusBtnX + kTransportPadX + (inner - tw) / 2;
  panel_text_on(x, gStatusBtnY + kTransportPadY, label, kTextSize, 0x0000,
                kWhite);
  copy_text(gPaintedLabel, sizeof(gPaintedLabel), label);
}

static void draw_status(void) {
  if (!gDisplayOk) {
    return;
  }
  place_transport_button();
  const char *label = transport_label();
  char volume[16];
  const int rot = gRotation;
  snprintf(volume, sizeof(volume), "vol %d", optimistic_volume());
  const char *texts[kLineCount] = {
      gAwake ? "spinme" : "asleep",
      gStatus,
      gArtist,
      gTitle,
      volume,
      gActivity,
  };
  const uint16_t colors[kLineCount] = {kYellow, kWhite, kWhite, kWhite, kWhite,
                                       kWhite};
  char shown[kLineCount][kLineChars];
  uint16_t shown_colors[kLineCount];
  int shown_section[kLineCount];
  int count = 0;
  for (int i = 0; i < kLineCount; ++i) {
    if (texts[i][0] == '\0') {
      continue;
    }
    copy_text(shown[count], sizeof(shown[count]), texts[i]);
    shown_colors[count] = colors[i];
    shown_section[count] = kLineSection[i];
    count++;
  }
  const bool label_same = strcmp(gPaintedLabel, label) == 0;
  bool lines_same = gPaintedCount == count;
  if (lines_same) {
    for (int i = 0; i < count; ++i) {
      if (strcmp(gPaintedLine[i], shown[i]) != 0) {
        lines_same = false;
        break;
      }
    }
  }
  gDrawnRotation = rot;
  if (label_same && lines_same) {
    return;
  }
  char fitted[kLineCount][kLineChars];
  uint16_t fitted_colors[kLineCount];
  int fitted_section[kLineCount];
  for (int i = 0; i < count; ++i) {
    copy_text(fitted[i], sizeof(fitted[i]), shown[i]);
    fitted_colors[i] = shown_colors[i];
    fitted_section[i] = shown_section[i];
  }
  const int fitted_count = fit_block(fitted, fitted_colors, fitted_section, count);
  /* Full frame into the back buffer. panel_present pushes changed spans.
   * Text first, then the button, so a tall block cannot erase the button. */
  panel_fill_screen(0x0000);
  if (fitted_count > 0) {
    LayAt placed[kPartCap];
    int slot[kLineCount];
    LayUnion block;
    compose_block(fitted, fitted_section, fitted_count, placed, &block, slot);
    const int ax = LCD_WIDTH / 2;
    const int ay = LCD_HEIGHT / 2;
    for (int i = 0; i < fitted_count; ++i) {
      if (slot[i] < 0) {
        continue;
      }
      const LayAt *at = &placed[slot[i]];
      panel_text(ax + lay_left(at), ay + lay_top(at), fitted[i], kTextSize,
                 fitted_colors[i]);
    }
  }
  paint_transport_button();
  for (int i = 0; i < count; ++i) {
    copy_text(gPaintedLine[i], sizeof(gPaintedLine[i]), shown[i]);
  }
  gPaintedCount = count;
  panel_present();
}

static bool pin_backlit(void) {
  return digitalRead(PIN_LCD_BL) == HIGH;
}

static void wake_display(void) {
  gLastActivityMs = millis();
  if (!gAwake || !pin_backlit()) {
    gAwake = true;
    digitalWrite(PIN_LCD_BL, HIGH);
  }
}

static void note_activity(const char *label) {
  wake_display();
  copy_text(gActivity, sizeof(gActivity), label);
  gUiDirty = true;
}

static bool json_string_field(const String &body, const char *key, char *out,
                              size_t out_len) {
  const String pat = String("\"") + key + "\":\"";
  const int start = body.indexOf(pat);
  if (start < 0) {
    out[0] = '\0';
    return false;
  }
  int i = start + pat.length();
  size_t n = 0;
  while (i < body.length() && body[i] != '"' && n + 1 < out_len) {
    out[n++] = body[i++];
  }
  out[n] = '\0';
  return n > 0;
}

static int json_int_field(const String &body, const char *key, int fallback) {
  const String pat = String("\"") + key + "\":";
  const int start = body.indexOf(pat);
  if (start < 0) {
    return fallback;
  }
  int i = start + pat.length();
  while (i < body.length() && (body[i] == ' ' || body[i] == '\t')) {
    i++;
  }
  bool neg = false;
  if (i < body.length() && body[i] == '-') {
    neg = true;
    i++;
  }
  if (i >= body.length() || body[i] < '0' || body[i] > '9') {
    return fallback;
  }
  int value = 0;
  while (i < body.length() && body[i] >= '0' && body[i] <= '9') {
    value = value * 10 + (body[i] - '0');
    i++;
  }
  return neg ? -value : value;
}

/* lwIP hostByName waits up to about 15s, and it is not covered by the HTTP
 * timeouts. Resolving the name on every request held the glass that long.
 * Keep the address and pass a literal IP so later calls skip DNS. */
static IPAddress gVolumioIp;
static bool gVolumioResolved = false;

static bool ensure_volumio_ip(void) {
  if (gVolumioResolved) {
    return true;
  }
  if (WiFi.status() != WL_CONNECTED) {
    return false;
  }
  if (!WiFi.hostByName(VOLUMIO_HOST, gVolumioIp) ||
      gVolumioIp == IPAddress((uint32_t)0)) {
    return false;
  }
  gVolumioResolved = true;
  Serial.printf("volumio %s\n", gVolumioIp.toString().c_str());
  return true;
}

static bool volumio_get(const String &path, String *body,
                         uint16_t timeout_ms = 2500) {
  if (!ensure_volumio_ip()) {
    return false;
  }
  HTTPClient http;
  if (!http.begin(gVolumioIp.toString(), kVolumioPort, path)) {
    gVolumioResolved = false;
    return false;
  }
  http.setConnectTimeout(1000);
  http.setTimeout(timeout_ms);
  const int code = http.GET();
  if (code == 200) {
    *body = http.getString();
  }
  http.end();
  if (code < 0) {
    gVolumioResolved = false;
  }
  return code == 200;
}

static bool refresh_player(void) {
  String body;
  if (!volumio_get("/api/v1/getState", &body)) {
    copy_text(gStatus, sizeof(gStatus), "player ?");
    return false;
  }
  json_string_field(body, "status", gStatus, sizeof(gStatus));
  json_string_field(body, "artist", gArtist, sizeof(gArtist));
  json_string_field(body, "title", gTitle, sizeof(gTitle));
  const int polled = json_int_field(body, "volume", gVolume);
  const bool hold = gUnsent != 0 || (gLastVolSendMs != 0 &&
                                     millis() - gLastVolSendMs < 1000);
  if (!hold) {
    gVolume = polled;
  }
  Serial.printf("state %s vol %d\n", gStatus, gVolume);
  return true;
}

/* CORRECTED 2026-10-15: the 2s poll was gated on gAwake, and
 * wake_display() only drove the backlight pin. A rising edge (or a
 * lit pin while gAwake is still false) is the wake event. */
/* Wake only marks state. The frame and the player refresh wait until the
 * knob has been quiet. The frame is drawn before any Volumio call. */
static void issue_wake(void) {
  gAwake = true;
  gLastActivityMs = millis();
  if (!pin_backlit()) {
    digitalWrite(PIN_LCD_BL, HIGH);
  }
  gPlayerRefresh = true;
  gUiDirty = true;
}

static void service_backlight(void) {
  static bool was_lit = true;
  const bool lit = pin_backlit();
  if (lit && (!was_lit || !gAwake)) {
    issue_wake();
  }
  was_lit = pin_backlit();
}

static void volumio_toggle(void) {
  String body;
  if (!volumio_get("/api/v1/commands/?cmd=toggle", &body)) {
    note_activity("toggle ?");
    return;
  }
  refresh_player();
  gUiDirty = true;
}

static void connect_wifi(void) {
  if (SPINME_WIFI_SSID[0] == '\0') {
    copy_text(gStatus, sizeof(gStatus), "wifi unset");
    draw_status();
    return;
  }
  copy_text(gStatus, sizeof(gStatus), "wifi ...");
  draw_status();
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(SPINME_WIFI_SSID, SPINME_WIFI_PASS);
  const uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    delay(200);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("wifi ok %s\n", WiFi.localIP().toString().c_str());
    copy_text(gStatus, sizeof(gStatus), "wifi ok");
    refresh_player();
  } else {
    Serial.println("wifi fail");
    copy_text(gStatus, sizeof(gStatus), "wifi fail");
  }
  draw_status();
}

static void touch_init(void) {
  pinMode(PIN_TOUCH_RST, OUTPUT);
  digitalWrite(PIN_TOUCH_RST, LOW);
  delay(10);
  digitalWrite(PIN_TOUCH_RST, HIGH);
  delay(50);
  Wire.begin(PIN_TOUCH_SDA, PIN_TOUCH_SCL);
  Wire.setClock(300000);
  Wire.beginTransmission(TOUCH_I2C_ADDR);
  Wire.write(0x00);
  Wire.write(0x00);
  const uint8_t err = Wire.endTransmission();
  pinMode(PIN_TOUCH_INT, INPUT_PULLUP);
  Serial.printf("touch init %u\n", err);
}

/* CST816: 7 bytes from reg 0x00. Finger count is byte 2. */
static bool touch_pressed(uint16_t *x, uint16_t *y) {
  Wire.beginTransmission(TOUCH_I2C_ADDR);
  Wire.write(0x00);
  if (Wire.endTransmission(false) != 0) {
    return false;
  }
  if (Wire.requestFrom(TOUCH_I2C_ADDR, 7) != 7) {
    return false;
  }
  Wire.read();
  Wire.read();
  const uint8_t fingers = Wire.read();
  const uint8_t xh = Wire.read();
  const uint8_t xl = Wire.read();
  const uint8_t yh = Wire.read();
  const uint8_t yl = Wire.read();
  if (fingers == 0) {
    return false;
  }
  *x = (static_cast<uint16_t>(xh & 0x0f) << 8) | xl;
  *y = (static_cast<uint16_t>(yh & 0x0f) << 8) | yl;
  /* Panel MADCTL is 180 deg. Map the touch into that same view. */
  if (*x < LCD_WIDTH) {
    *x = static_cast<uint16_t>(LCD_WIDTH - 1 - *x);
  }
  if (*y < LCD_HEIGHT) {
    *y = static_cast<uint16_t>(LCD_HEIGHT - 1 - *y);
  }
  return true;
}

static void reply_query(void) {
  char player[sizeof(gStatus)];
  size_t i = 0;
  for (; gStatus[i] != '\0' && i + 1 < sizeof(player); ++i) {
    player[i] = (gStatus[i] == ' ') ? '_' : gStatus[i];
  }
  player[i] = '\0';
  const int backlight = digitalRead(PIN_LCD_BL) == HIGH ? 1 : 0;
  const uint32_t idle_ms = millis() - gLastActivityMs;
  /* GPIO1 is ADC1. Reading it powers the SAR, and GPIO7/GPIO8 (the
   * encoder) are ADC1 pins too. After that read they chatter, and the
   * chatter was putting the backlight to sleep. */
  Serial.printf(
      "query backlight=%d awake=%d idle_ms=%lu idle_sleep=%d cpu_sleep=0 "
      "wifi=%s player=%s volume=%d rotation=%d system_mv=na "
      "power_w=unavailable\n",
      backlight, gAwake ? 1 : 0, static_cast<unsigned long>(idle_ms),
      gAwake ? 0 : 1, WiFi.status() == WL_CONNECTED ? "connected" : "down",
      player, gVolume, (int)gRotation);
}

static void service_query(void) {
  static char buf[8];
  static size_t n = 0;
  while (Serial.available() > 0) {
    const int c = Serial.read();
    if (c < 0) {
      return;
    }
    if (c == '\n' || c == '\r') {
      buf[n] = '\0';
      if (strcmp(buf, "query") == 0) {
        reply_query();
      }
      n = 0;
      continue;
    }
    if (n + 1 < sizeof(buf)) {
      buf[n++] = static_cast<char>(c);
    } else {
      n = 0;
    }
  }
}

static void take_rotation(void) {
  const int rot = gRotation;
  const int delta = rot - gTakenRot;
  gTakenRot = rot;
  if (delta == 0) {
    return;
  }
  if (gUnsent == 0) {
    gVolArmMs = millis();
  }
  gUnsent += delta;
  gLastInputMs = millis();
  gUiDirty = true;
  wake_display();
}

/* One absolute volume write. A short gather folds a flick into the first
 * request, then further sends wait kVolSendGapMs so a fast spin does not
 * become one HTTP call per detent. */
static void flush_volume(void) {
  if (gUnsent == 0 || gVolume < 0 || WiFi.status() != WL_CONNECTED) {
    return;
  }
  const uint32_t now = millis();
  if (now - gVolArmMs < kVolGatherMs) {
    return;
  }
  if (gLastVolSendMs != 0 && now - gLastVolSendMs < kVolSendGapMs) {
    return;
  }
  int target = gVolume + gUnsent;
  if (target < 0) {
    target = 0;
  }
  if (target > 100) {
    target = 100;
  }
  const int snap = gUnsent;
  if (target == gVolume) {
    gUnsent -= snap;
    return;
  }
  char path[72];
  snprintf(path, sizeof(path), "/api/v1/commands/?cmd=volume&volume=%d", target);
  String body;
  gLastVolSendMs = now;
  if (!volumio_get(path, &body, 800)) {
    Serial.printf("vol send fail %d\n", target);
    return;
  }
  Serial.printf("vol send %d (%+d)\n", target, snap);
  gVolume = target;
  gUnsent -= snap;
}

static void IRAM_ATTR on_encoder(void) {
  const uint32_t now = static_cast<uint32_t>(esp_timer_get_time());
  const uint8_t prev = gEncLast;
  const uint8_t cur =
      (static_cast<uint8_t>(gpio_get_level(static_cast<gpio_num_t>(PIN_ENC_A)))
       << 1) |
      static_cast<uint8_t>(gpio_get_level(static_cast<gpio_num_t>(PIN_ENC_B)));
  gEncLast = cur;
  int8_t step = 0;
  encoder_on_edge(prev, cur, now, &gClickPin, &gClickLockUs, &gClickHighUs,
                  &gRotation, &step);
  const uint16_t w = gEncLogW;
  const uint16_t next = static_cast<uint16_t>((w + 1) % kEncLogCap);
  if (next == gEncLogR) {
    gEncDrop++;
    return;
  }
  EncEdge *edge = &gEncLog[w];
  edge->us = static_cast<uint32_t>(esp_timer_get_time());
  edge->prev = prev;
  edge->cur = cur;
  edge->step = step;
  edge->rot = gRotation;
  gEncLogW = next;
}

static void drain_enc_log(void) {
  while (gEncLogR != gEncLogW) {
    const EncEdge edge = gEncLog[gEncLogR];
    gEncLogR = static_cast<uint16_t>((gEncLogR + 1) % kEncLogCap);
    Serial.printf("enc us=%lu prev=%u cur=%u step=%d rot=%d\n",
                  static_cast<unsigned long>(edge.us), edge.prev, edge.cur,
                  edge.step, edge.rot);
  }
  if (gEncDrop != 0) {
    Serial.printf("enc drop=%u\n", static_cast<unsigned>(gEncDrop));
    gEncDrop = 0;
  }
}

static void encoder_begin(void) {
  pinMode(PIN_ENC_A, INPUT_PULLUP);
  pinMode(PIN_ENC_B, INPUT_PULLUP);
  gEncLast =
      (static_cast<uint8_t>(gpio_get_level(static_cast<gpio_num_t>(PIN_ENC_A)))
       << 1) |
      static_cast<uint8_t>(gpio_get_level(static_cast<gpio_num_t>(PIN_ENC_B)));
  attachInterrupt(PIN_ENC_A, on_encoder, CHANGE);
  attachInterrupt(PIN_ENC_B, on_encoder, CHANGE);
  Serial.printf("enc init ab=%u\n", gEncLast);
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.printf("spinme: %s (%s)\n", BOARD_NAME, BOARD_SKU);

  pinMode(PIN_LCD_BL, OUTPUT);
  digitalWrite(PIN_LCD_BL, HIGH);
  gLastActivityMs = millis();

  gDisplayOk = panel_begin();
  Serial.printf("display begin %s\n", gDisplayOk ? "ok" : "fail");
  if (gDisplayOk) {
    panel_apply_waveshare_init();
    Serial.println("panel vendor init");
    Serial.println(panel_buffers_begin() ? "framebuffer on" : "framebuffer off");
    draw_status();
  }

  touch_init();
  encoder_begin();
  connect_wifi();
}

static bool ui_busy(void) {
  return millis() - gLastInputMs < kUiQuietMs;
}

static void paint_if_dirty(void) {
  if (!gUiDirty || !pin_backlit()) {
    return;
  }
  const int rot = gRotation;
  const int unsent = gUnsent;
  draw_status();
  if ((int)gRotation == rot && gUnsent == unsent && gDrawnRotation == rot) {
    gUiDirty = false;
  }
}

/* Slow work waits until the knob and touch have been quiet. Paint the
 * accumulated volume before Volumio HTTP, so a slow getState cannot hide
 * a turn that already happened. */
static void service_deferred(void) {
  if (ui_busy()) {
    return;
  }
  drain_enc_log();
  paint_if_dirty();
  if (pin_backlit() && WiFi.status() == WL_CONNECTED &&
      (gPlayerRefresh || millis() - gLastPollMs > 2000)) {
    gLastPollMs = millis();
    gPlayerRefresh = false;
    refresh_player();
    gUiDirty = true;
  }
  const int unsent_before = gUnsent;
  flush_volume();
  if (gUnsent != unsent_before) {
    gUiDirty = true;
  }
  paint_if_dirty();
}

void loop() {
  take_rotation();
  service_query();
  uint16_t x = 0;
  uint16_t y = 0;
  static bool was_touch = false;
  const bool pressed = touch_pressed(&x, &y);
  if (pressed && !was_touch) {
    Serial.printf("touch %u %u\n", x, y);
    gTouchCount++;
    gLastInputMs = millis();
    const bool was_asleep = !gAwake;
    const bool on_button = !was_asleep && status_button_hit(x, y);
    note_activity("touch");
    if (on_button) {
      volumio_toggle();
    } else if (!was_asleep && WiFi.status() == WL_CONNECTED) {
      gPlayerRefresh = true;
      gUiDirty = true;
    }
  }
  was_touch = pressed;

  static uint8_t last_ab = 0xff;
  const uint8_t ab = (static_cast<uint8_t>(digitalRead(PIN_ENC_A)) << 1) |
                     static_cast<uint8_t>(digitalRead(PIN_ENC_B));
  if (ab != last_ab) {
    last_ab = ab;
    gLastInputMs = millis();
    wake_display();
  }

  /* Read millis() again. A sample from the top of this pass is older
   * than gLastActivityMs, and the unsigned subtract wraps into sleep. */
  if (gAwake && millis() - gLastActivityMs > kIdleSleepMs) {
    gAwake = false;
    digitalWrite(PIN_LCD_BL, LOW);
    Serial.println("sleep");
    gUiDirty = true;
  }

  service_backlight();
  service_deferred();
  delay(10);
}
