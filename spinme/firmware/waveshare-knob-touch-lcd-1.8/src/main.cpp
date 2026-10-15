#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <stdio.h>
#include <string.h>

#include "board_pins.h"
#include "panel_init.h"
#include "panel_io.h"
#include "wifi_local.h"

#ifndef VOLUMIO_HOST
#define VOLUMIO_HOST "miniDSP-SHD.local"
#endif

static const uint16_t kVolumioPort = 3000;
static const uint32_t kIdleSleepMs = 30000;
static const int kEncoderDetent = 4;
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
static uint16_t gTouchCount = 0;
static int gKnobCount = 0;

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
 * screenmock/layout.py: six centered lines, cell 6x8 times text size.
 */
static const int kTextSize = 2;
static const int kGlyphW = 6;
static const int kGlyphH = 8;
static const int kLineCount = 6;

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

static void fit_line(char *text, int y) {
  const int cell_w = kGlyphW * kTextSize;
  const int cell_h = kGlyphH * kTextSize;
  size_t n = strlen(text);
  while (n > 0) {
    const int w = static_cast<int>(n) * cell_w;
    const int x = (LCD_WIDTH - w) / 2;
    if (box_inside_circle(x, y, w, cell_h)) {
      return;
    }
    n--;
    text[n] = '\0';
  }
}

static void draw_centered(const char *text, int y, uint16_t color) {
  char buf[64];
  copy_text(buf, sizeof(buf), text);
  fit_line(buf, y);
  if (buf[0] == '\0') {
    return;
  }
  const int w = static_cast<int>(strlen(buf)) * kGlyphW * kTextSize;
  const int x = (LCD_WIDTH - w) / 2;
  panel_text(x, y, buf, kTextSize, color);
}

static void draw_status(void) {
  if (!gDisplayOk) {
    return;
  }
  panel_fill_screen(0x0000);
  const int line_h = kGlyphH * kTextSize;
  char volume[16];
  snprintf(volume, sizeof(volume), "vol %d", gVolume);
  const char *texts[kLineCount] = {
      gAwake ? "spinme" : "asleep",
      gStatus,
      gArtist,
      gTitle,
      volume,
      gActivity,
  };
  const uint16_t colors[kLineCount] = {kYellow, kWhite, kWhite, kWhite, kWhite, kWhite};
  const char *shown[kLineCount];
  uint16_t shown_colors[kLineCount];
  int count = 0;
  for (int i = 0; i < kLineCount; ++i) {
    if (texts[i][0] == '\0') {
      continue;
    }
    shown[count] = texts[i];
    shown_colors[count] = colors[i];
    count++;
  }
  const int y0 = (LCD_HEIGHT - count * line_h) / 2;
  for (int i = 0; i < count; ++i) {
    draw_centered(shown[i], y0 + i * line_h, shown_colors[i]);
  }
}

static void wake_display(void) {
  gLastActivityMs = millis();
  if (!gAwake) {
    gAwake = true;
    digitalWrite(PIN_LCD_BL, HIGH);
  }
}

static void note_activity(const char *label) {
  wake_display();
  copy_text(gActivity, sizeof(gActivity), label);
  draw_status();
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

static bool volumio_get(const String &path, String *body) {
  if (WiFi.status() != WL_CONNECTED) {
    return false;
  }
  HTTPClient http;
  const String url =
      String("http://") + VOLUMIO_HOST + ":" + String(kVolumioPort) + path;
  http.setTimeout(2500);
  http.begin(url);
  const int code = http.GET();
  if (code == 200) {
    *body = http.getString();
  }
  http.end();
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
  gVolume = json_int_field(body, "volume", gVolume);
  Serial.printf("state %s vol %d\n", gStatus, gVolume);
  return true;
}

static void volumio_volume_step(int direction) {
  if (WiFi.status() != WL_CONNECTED) {
    note_activity(direction > 0 ? "knob +" : "knob -");
    return;
  }
  note_activity(direction > 0 ? "knob +" : "knob -");
  String body;
  const char *step = direction > 0 ? "plus" : "minus";
  const String path =
      String("/api/v1/commands/?cmd=volume&volume=") + step;
  if (volumio_get(path, &body)) {
    refresh_player();
    draw_status();
  }
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
      "wifi=%s player=%s volume=%d system_mv=na power_w=unavailable\n",
      backlight, gAwake ? 1 : 0, static_cast<unsigned long>(idle_ms),
      gAwake ? 0 : 1, WiFi.status() == WL_CONNECTED ? "connected" : "down",
      player, gVolume);
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

static int encoder_delta(void) {
  static uint8_t last = 0;
  static int acc = 0;
  static const int8_t kTable[16] = {0, -1, 1, 0, 1, 0, 0, -1,
                                    -1, 0,  0, 1, 0, 1, -1, 0};
  const uint8_t cur = (static_cast<uint8_t>(digitalRead(PIN_ENC_A)) << 1) |
                      static_cast<uint8_t>(digitalRead(PIN_ENC_B));
  const int8_t step = kTable[((last << 2) | cur) & 0x0f];
  last = cur;
  if (step == 0) {
    return 0;
  }
  gKnobCount += step;
  acc += step;
  if (acc >= kEncoderDetent) {
    acc = 0;
    return 1;
  }
  if (acc <= -kEncoderDetent) {
    acc = 0;
    return -1;
  }
  return 0;
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
    draw_status();
  }

  touch_init();
  pinMode(PIN_ENC_A, INPUT_PULLUP);
  pinMode(PIN_ENC_B, INPUT_PULLUP);
  encoder_delta();
  connect_wifi();
}

void loop() {
  service_query();
  const uint32_t now = millis();
  uint16_t x = 0;
  uint16_t y = 0;
  static bool was_touch = false;
  const bool pressed = touch_pressed(&x, &y);
  if (pressed && !was_touch) {
    Serial.printf("touch %u %u\n", x, y);
    gTouchCount++;
    const bool was_asleep = !gAwake;
    note_activity("touch");
    if (was_asleep || WiFi.status() == WL_CONNECTED) {
      refresh_player();
      draw_status();
    }
  }
  was_touch = pressed;

  const int delta = encoder_delta();
  if (delta != 0) {
    Serial.printf("enc %d k %d\n", delta, gKnobCount);
    volumio_volume_step(delta);
  } else if (gKnobCount != 0) {
    static int shown_knob = 0;
    if (shown_knob != gKnobCount) {
      shown_knob = gKnobCount;
      wake_display();
      draw_status();
    }
  }

  static uint8_t last_ab = 0xff;
  const uint8_t ab = (static_cast<uint8_t>(digitalRead(PIN_ENC_A)) << 1) |
                     static_cast<uint8_t>(digitalRead(PIN_ENC_B));
  if (ab != last_ab) {
    last_ab = ab;
    Serial.printf("ab %u\n", ab);
    wake_display();
    draw_status();
  }

  /* Sample millis() here. wake_display() above stores a newer tick, and
   * subtracting that from the older `now` wraps and trips this immediately. */
  if (gAwake && millis() - gLastActivityMs > kIdleSleepMs) {
    gAwake = false;
    digitalWrite(PIN_LCD_BL, LOW);
    Serial.println("sleep");
  }

  static uint32_t last_poll = 0;
  if (gAwake && WiFi.status() == WL_CONNECTED && now - last_poll > 2000) {
    last_poll = now;
    if (refresh_player()) {
      draw_status();
    }
  }
  delay(10);
}
