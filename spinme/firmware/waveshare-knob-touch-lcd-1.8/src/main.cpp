#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <driver/gpio.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
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
/* Second ink for the knob target, drawn at half alpha over the polled volume. */
static const uint16_t kDesiredInk = 0x07FF;
static const int kDesiredAlpha = 128;
static const uint32_t kPollMs = 1000;

static bool gDisplayOk = false;
static bool gAwake = true;
static uint32_t gLastActivityMs = 0;
static char gActivity[32] = "";
static int gTakenRot = 0;
/* Last good player fields. volume is what Volumio last reported.
 * desired is the knob target. They differ until a later poll catches up. */
struct Snap {
  char status[24];
  char artist[48];
  char title[48];
  char link[16];
  int volume;
  bool have_player;
};
static Snap gWorkerSnap = {"", "", "", "boot", -1, false};
static Snap gPublished = {"", "", "", "boot", -1, false};
static portMUX_TYPE gSnapMux = portMUX_INITIALIZER_UNLOCKED;
static volatile uint32_t gSnapSeq = 0;
struct Mail {
  bool poll;
  bool toggle;
  bool has_volume;
  int volume;
};
static Mail gMail = {false, false, false, 0};
static portMUX_TYPE gMailMux = portMUX_INITIALIZER_UNLOCKED;
static TaskHandle_t gWorker = nullptr;
static int gDesired = -1;
static bool gDesiredHeld = false;
static int gUnapplied = 0;
static int gPaintedDesired = -999;
static uint32_t gLastPollPost = 0;
static bool gWakePoll = true;
static uint32_t gSeenSeq = 0;
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
static uint32_t gLastInputMs = 0;
static bool gUiDirty = false;
/* Paint waits this long after the last knob or touch edge. The encoder's
 * other-pin lock stays 200 ms. Volumio work is not on this core. */
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

static void publish_snap(void) {
  portENTER_CRITICAL(&gSnapMux);
  gPublished = gWorkerSnap;
  gSnapSeq++;
  portEXIT_CRITICAL(&gSnapMux);
}

static Snap read_snap(void) {
  Snap snap;
  portENTER_CRITICAL(&gSnapMux);
  snap = gPublished;
  portEXIT_CRITICAL(&gSnapMux);
  return snap;
}

static void wake_worker(void) {
  if (gWorker != nullptr) {
    xTaskNotifyGive(gWorker);
  }
}

static void post_mail_poll(void) {
  portENTER_CRITICAL(&gMailMux);
  gMail.poll = true;
  portEXIT_CRITICAL(&gMailMux);
  wake_worker();
}

static void post_mail_toggle(void) {
  portENTER_CRITICAL(&gMailMux);
  gMail.toggle = true;
  portEXIT_CRITICAL(&gMailMux);
  wake_worker();
}

static void post_mail_volume(int volume) {
  portENTER_CRITICAL(&gMailMux);
  gMail.has_volume = true;
  gMail.volume = volume;
  portEXIT_CRITICAL(&gMailMux);
  wake_worker();
}

static int clamp_volume(int volume) {
  if (volume < 0) {
    return 0;
  }
  if (volume > 100) {
    return 100;
  }
  return volume;
}

/* No outstanding turn: desired tracks the poll. A held target stays until
 * the polled volume equals it. Steps from before the first poll apply once. */
static void adopt_snap(const Snap &snap) {
  if (snap.volume < 0 || !snap.have_player) {
    return;
  }
  if (!gDesiredHeld) {
    if (gUnapplied != 0) {
      gDesired = clamp_volume(snap.volume + gUnapplied);
      gUnapplied = 0;
      gDesiredHeld = gDesired != snap.volume;
      if (gDesiredHeld) {
        post_mail_volume(gDesired);
      }
    } else {
      gDesired = snap.volume;
    }
    return;
  }
  if (snap.volume == gDesired) {
    gDesiredHeld = false;
  }
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

/* Shorten the widest line until every left-aligned line is in the circle.
 * A wide title sets the shared left edge. Chopping that line pulls the
 * edge back in. Chopping a short line that merely shares the edge would
 * erase spinme, the player, or the volume. */
static int fit_block(char lines[][kLineChars], uint16_t *colors, int *sections,
                     int count) {
  while (count > 0) {
    LayAt placed[kPartCap];
    int slot[kLineCount];
    LayUnion block;
    compose_block(lines, sections, count, placed, &block, slot);
    const int ax = LCD_WIDTH / 2;
    const int ay = LCD_HEIGHT / 2;
    int widest = -1;
    int widest_w = -1;
    bool outside = false;
    for (int i = 0; i < count; ++i) {
      if (slot[i] < 0) {
        widest = i;
        widest_w = 100000;
        outside = true;
        break;
      }
      const LayAt *at = &placed[slot[i]];
      if (at->w > widest_w) {
        widest = i;
        widest_w = at->w;
      }
      const int left = ax + lay_left(at);
      const int top = ay + lay_top(at);
      if (!box_inside_circle(left, top, at->w, at->h)) {
        outside = true;
      }
    }
    if (!outside || widest < 0) {
      return count;
    }
    const size_t n = strlen(lines[widest]);
    if (n == 0 || slot[widest] < 0) {
      drop_line(lines, colors, sections, count, widest);
      count--;
      continue;
    }
    lines[widest][n - 1] = '\0';
    if (lines[widest][0] == '\0') {
      drop_line(lines, colors, sections, count, widest);
      count--;
    }
  }
  return count;
}

static const char *transport_label(const char *status) {
  if (status != nullptr && strcmp(status, "play") == 0) {
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

static void paint_transport_button(const char *status) {
  const char *label = transport_label(status);
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
  const Snap snap = read_snap();
  adopt_snap(snap);
  const char *player = snap.have_player ? snap.status : snap.link;
  place_transport_button();
  const char *label = transport_label(player);
  char volume[16] = "";
  char desire[16] = "";
  const bool overlay =
      gDesiredHeld && snap.volume >= 0 && gDesired != snap.volume;
  if (snap.volume >= 0) {
    snprintf(volume, sizeof(volume), "vol %d", snap.volume);
  }
  if (overlay) {
    snprintf(desire, sizeof(desire), "vol %d", gDesired);
  }
  const char *texts[kLineCount] = {
      gAwake ? "spinme" : "asleep",
      player,
      snap.artist,
      snap.title,
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
  const int painted_desire = overlay ? gDesired : -1;
  const bool label_same = strcmp(gPaintedLabel, label) == 0;
  bool lines_same = gPaintedCount == count && gPaintedDesired == painted_desire;
  if (lines_same) {
    for (int i = 0; i < count; ++i) {
      if (strcmp(gPaintedLine[i], shown[i]) != 0) {
        lines_same = false;
        break;
      }
    }
  }
  gDrawnRotation = gRotation;
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
      const int left = ax + lay_left(at);
      const int top = ay + lay_top(at);
      panel_text(left, top, fitted[i], kTextSize, fitted_colors[i]);
      if (overlay && strncmp(fitted[i], "vol ", 4) == 0) {
        panel_text_over(left, top, desire, kTextSize, kDesiredInk, kDesiredAlpha);
      }
    }
  }
  paint_transport_button(player);
  for (int i = 0; i < count; ++i) {
    copy_text(gPaintedLine[i], sizeof(gPaintedLine[i]), shown[i]);
  }
  gPaintedCount = count;
  gPaintedDesired = painted_desire;
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
    return false;
  }
  json_string_field(body, "status", gWorkerSnap.status, sizeof(gWorkerSnap.status));
  json_string_field(body, "artist", gWorkerSnap.artist, sizeof(gWorkerSnap.artist));
  json_string_field(body, "title", gWorkerSnap.title, sizeof(gWorkerSnap.title));
  gWorkerSnap.volume = json_int_field(body, "volume", gWorkerSnap.volume);
  gWorkerSnap.have_player = true;
  Serial.printf("state %s vol %d\n", gWorkerSnap.status, gWorkerSnap.volume);
  publish_snap();
  return true;
}

/* CORRECTED 2026-10-15: the 2s poll was gated on gAwake, and
 * wake_display() only drove the backlight pin. A rising edge (or a
 * lit pin while gAwake is still false) is the wake event. */
/* Wake marks the glass. The UI core posts one poll, then the one-second
 * loop, until the backlight is off again. */
static void issue_wake(void) {
  gAwake = true;
  gLastActivityMs = millis();
  if (!pin_backlit()) {
    digitalWrite(PIN_LCD_BL, HIGH);
  }
  gWakePoll = true;
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

static bool send_volume(int target) {
  char path[72];
  snprintf(path, sizeof(path), "/api/v1/commands/?cmd=volume&volume=%d", target);
  String body;
  if (!volumio_get(path, &body, 800)) {
    Serial.printf("vol send fail %d\n", target);
    return false;
  }
  Serial.printf("vol send %d\n", target);
  return true;
}

static void connect_wifi(void) {
  if (SPINME_WIFI_SSID[0] == '\0') {
    copy_text(gWorkerSnap.link, sizeof(gWorkerSnap.link), "wifi unset");
    publish_snap();
    return;
  }
  copy_text(gWorkerSnap.link, sizeof(gWorkerSnap.link), "wifi ...");
  publish_snap();
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(SPINME_WIFI_SSID, SPINME_WIFI_PASS);
  const uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    delay(200);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("wifi ok %s\n", WiFi.localIP().toString().c_str());
    copy_text(gWorkerSnap.link, sizeof(gWorkerSnap.link), "wifi ok");
    publish_snap();
    refresh_player();
  } else {
    Serial.println("wifi fail");
    copy_text(gWorkerSnap.link, sizeof(gWorkerSnap.link), "wifi fail");
    publish_snap();
  }
}

static void worker_task(void *arg) {
  (void)arg;
  connect_wifi();
  for (;;) {
    ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(200));
    Mail mail;
    portENTER_CRITICAL(&gMailMux);
    mail = gMail;
    gMail.poll = false;
    gMail.toggle = false;
    portEXIT_CRITICAL(&gMailMux);
    if (mail.toggle) {
      String body;
      volumio_get("/api/v1/commands/?cmd=toggle", &body);
      refresh_player();
    }
    if (mail.has_volume) {
      const bool ok = send_volume(mail.volume);
      portENTER_CRITICAL(&gMailMux);
      if (ok && gMail.volume == mail.volume) {
        gMail.has_volume = false;
      }
      portEXIT_CRITICAL(&gMailMux);
    }
    if (mail.poll) {
      refresh_player();
    }
  }
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
  const Snap snap = read_snap();
  const char *shown = snap.have_player ? snap.status : snap.link;
  char player[sizeof(snap.status)];
  size_t i = 0;
  for (; shown[i] != '\0' && i + 1 < sizeof(player); ++i) {
    player[i] = (shown[i] == ' ') ? '_' : shown[i];
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
      player, snap.volume, (int)gRotation);
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
  const Snap snap = read_snap();
  if (!snap.have_player || snap.volume < 0) {
    gUnapplied += delta;
  } else {
    if (!gDesiredHeld) {
      gDesired = snap.volume;
    }
    gDesired = clamp_volume(gDesired + delta);
    gDesiredHeld = gDesired != snap.volume;
    if (gDesiredHeld) {
      post_mail_volume(gDesired);
    }
  }
  gLastInputMs = millis();
  gUiDirty = true;
  wake_display();
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
  xTaskCreatePinnedToCore(worker_task, "volumio", 16384, nullptr, 1, &gWorker, 0);
}

static bool ui_busy(void) {
  return millis() - gLastInputMs < kUiQuietMs;
}

static void service_deferred(void) {
  if (ui_busy()) {
    return;
  }
  drain_enc_log();
  if (gSnapSeq != gSeenSeq) {
    gSeenSeq = gSnapSeq;
    gUiDirty = true;
  }
  if (!gUiDirty || !pin_backlit()) {
    return;
  }
  const int rot = gRotation;
  const bool held = gDesiredHeld;
  const int desired = gDesired;
  draw_status();
  if ((int)gRotation == rot && gDesiredHeld == held && gDesired == desired &&
      gDrawnRotation == rot) {
    gUiDirty = false;
  }
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
      post_mail_toggle();
    } else if (!was_asleep) {
      post_mail_poll();
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
  if (pin_backlit() && (gWakePoll || millis() - gLastPollPost >= kPollMs)) {
    gWakePoll = false;
    gLastPollPost = millis();
    post_mail_poll();
  }
  service_deferred();
  delay(10);
}
