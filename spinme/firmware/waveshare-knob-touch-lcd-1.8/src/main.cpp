#include <Arduino.h>
#include <Wire.h>
#include <driver/gpio.h>
#include <esp_heap_caps.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <stdlib.h>
#include <string.h>

#include "bench_probe.h"
#include "board_pins.h"
#include "encoder_decode.h"
#include "follow_glass.h"
#include "panel_init.h"
#include "panel_io.h"
#include "player_http.h"
#include "rom_jpeg.h"

extern "C" {
#include "uimk2_blit.h"
#include "uimk2_host.h"
}

static_assert((int)PANEL_W == LCD_WIDTH, "framebuffer width");
static_assert((int)PANEL_H == LCD_HEIGHT, "framebuffer height");

/* Boot stand-in until player HTTP fills the polled volume. */
static const int kBootVolume = 10;

static uimk2_ring gRing;
static uimk2_host gHost;
static uimk2_zlist gZ;
static uint8_t *gCurr = nullptr;
static uint8_t *gNext = nullptr;
static SemaphoreHandle_t gMu = nullptr;
static TaskHandle_t gUiTask = nullptr;
static TaskHandle_t gWorker = nullptr;
static volatile bool gBacklight = true;
static int gPolled = kBootVolume;
static int gDesiredA = kBootVolume;
static bool gDisplayOk = false;
static bool gBuilt = false;
/* False until a knob volume event commands the player. Polls before that
 * copy the player volume onto desired so the boot stand-in does not stick. */
static bool gVolumeSent = false;

static volatile int gRotation = 0;
static volatile uint8_t gEncLast = 0;
static volatile uint8_t gClickPin = 0;
static volatile uint32_t gClickLockUs = 0;
static volatile uint32_t gClickHighUs = 0;
static int gTakenRot = 0;

extern "C" void ping_core_a(void *ctx) {
  (void)ctx;
  __sync_synchronize();
  if (gUiTask != nullptr) {
    xTaskNotifyGive(gUiTask);
  }
}

static int isqrt_u32(uint32_t n) {
  uint32_t x;
  uint32_t y;
  if (n == 0u) {
    return 0;
  }
  x = n;
  y = (x + 1u) / 2u;
  while (y < x) {
    x = y;
    y = (x + n / x) / 2u;
  }
  return (int)x;
}

/* Square framebuffer, round bezel. x0..x1 inclusive. */
static bool bezel_span(int y, int *x0, int *x1) {
  const int r = LCD_WIDTH / 2;
  const int c = LCD_WIDTH / 2;
  const int dy = y - c;
  int disc;
  int half;
  int left;
  int right;
  if (dy < -r || dy > r) {
    return false;
  }
  disc = r * r - dy * dy;
  if (disc < 0) {
    return false;
  }
  half = isqrt_u32((uint32_t)disc);
  left = c - half;
  right = c + half;
  if (left < 0) {
    left = 0;
  }
  if (right >= LCD_WIDTH) {
    right = LCD_WIDTH - 1;
  }
  if (left > right) {
    return false;
  }
  *x0 = left;
  *x1 = right;
  return true;
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

static void notify_b(void) {
  if (gWorker != nullptr) {
    xTaskNotifyGive(gWorker);
  }
}

static void paint_follow(void) {
  int desired;
  bool playing;
  int polled;
  uint32_t now;
  xSemaphoreTake(gMu, portMAX_DELAY);
  desired = gHost.desired;
  playing = gHost.playing;
  polled = gPolled;
  now = gHost.now;
  if (gBuilt) {
    /* System clock from the host tick; CLOCKTEXT / SCROLL read it in update. */
    uimk2_zlist_set_clock(&gZ, (int32_t)(now / CLOCKS_PER_SEC_TICKS), now);
    uimk2_zlist_update(&gZ);
  }
  xSemaphoreGive(gMu);
  follow_glass_raster(polled, desired, playing, desired != polled);
}

static char gLastAlbumart[256];
static volatile bool gDecodeBusy = false;

struct DecodeJob {
  uint8_t *jpeg;
  size_t nbytes;
};

static void albumart_decode_task(void *arg) {
  DecodeJob *job = static_cast<DecodeJob *>(arg);
  uint8_t *bg = follow_glass_bg_rgba();
  RomJpegInfo ji;
  if (job == nullptr) {
    gDecodeBusy = false;
    vTaskDelete(nullptr);
    return;
  }
  if (bg == nullptr) {
    Serial.println("albumart bg null");
  } else if (!rom_jpeg_decode_nn_rgba(job->jpeg, job->nbytes, bg,
                                      (uint16_t)PANEL_W, (uint16_t)PANEL_H,
                                      &ji)) {
    Serial.printf("albumart romjpeg fail prep=%d decomp=%d ms=%u\n",
                  ji.jd_prepare, ji.jd_decomp, (unsigned)ji.decode_ms);
  } else {
    follow_glass_bg_mark_dirty();
    Serial.printf(
        "albumart romjpeg ok src=%ux%u via=%ux%u scale=1/%u "
        "dst=%ux%u decode_ms=%u\n",
        (unsigned)ji.src_w, (unsigned)ji.src_h, (unsigned)ji.out_w,
        (unsigned)ji.out_h, 1u << ji.scale, (unsigned)ji.dst_w,
        (unsigned)ji.dst_h, (unsigned)ji.decode_ms);
  }
  free(job->jpeg);
  free(job);
  gDecodeBusy = false;
  notify_b();
  vTaskDelete(nullptr);
}

static void on_getstate_ok(void) {
  const PlayerSnapshot *snap = player_http_snapshot();
  int shown;
  if (snap == nullptr) {
    return;
  }
  follow_glass_set_track(snap->artist, snap->album, snap->title);
  xSemaphoreTake(gMu, portMAX_DELAY);
  if (snap->volume >= 0) {
    gPolled = snap->volume;
    if (!gVolumeSent && gDesiredA == gHost.desired) {
      gHost.desired = gPolled;
      gDesiredA = gPolled;
    }
  }
  if (snap->have_status) {
    gHost.playing = snap->playing;
  }
  shown = gPolled;
  xSemaphoreGive(gMu);
  paint_follow();
  Serial.printf("player poll %s vol %d\n",
                snap->status[0] != '\0' ? snap->status : "?", shown);
  if (snap->albumart[0] != '\0' &&
      strncmp(snap->albumart, gLastAlbumart, sizeof gLastAlbumart) != 0) {
    (void)player_http_request_albumart(snap->albumart, 512u * 1024u);
  }
}

static void on_albumart_ok(void) {
  uint8_t *jpeg = nullptr;
  size_t nbytes = 0;
  uint32_t fetch_ms = 0;
  DecodeJob *job;
  const PlayerSnapshot *snap = player_http_snapshot();
  if (!player_http_take_albumart(&jpeg, &nbytes, &fetch_ms)) {
    return;
  }
  Serial.printf("albumart fetch %u bytes %u ms\n", (unsigned)nbytes,
                (unsigned)fetch_ms);
  if (snap != nullptr) {
    strncpy(gLastAlbumart, snap->albumart, sizeof gLastAlbumart - 1u);
    gLastAlbumart[sizeof gLastAlbumart - 1u] = '\0';
  }
  if (gDecodeBusy) {
    free(jpeg);
    return;
  }
  job = static_cast<DecodeJob *>(malloc(sizeof *job));
  if (job == nullptr) {
    free(jpeg);
    return;
  }
  job->jpeg = jpeg;
  job->nbytes = nbytes;
  gDecodeBusy = true;
  if (xTaskCreate(albumart_decode_task, "albumart", 8192, job, 1, nullptr) !=
      pdPASS) {
    gDecodeBusy = false;
    free(jpeg);
    free(job);
  }
}

static void pump_player_http(void) {
  PlayerHttpEvent ev = player_http_tick();
  if (ev == PLAYER_HTTP_EV_GETSTATE_OK) {
    on_getstate_ok();
  } else if (ev == PLAYER_HTTP_EV_GETSTATE_FAIL) {
    Serial.println("player poll fail");
  } else if (ev == PLAYER_HTTP_EV_ALBUMART_OK) {
    on_albumart_ok();
  } else if (ev == PLAYER_HTTP_EV_ALBUMART_FAIL) {
    Serial.println("albumart fetch fail");
  } else if (ev == PLAYER_HTTP_EV_CMD_FAIL) {
    Serial.println("player cmd fail");
  }
}

/* Caller holds gMu. A dark tap or detent posts screen_on and lights the pin. */
static void wake_locked(void) {
  if (gBacklight) {
    return;
  }
  gBacklight = true;
  (void)uimk2_post_screen_on(&gRing);
  digitalWrite(PIN_LCD_BL, HIGH);
}

static void core_a_push(void) {
  uint8_t *frame;
  int rows = 0;
  int y;
  if (!gBuilt || !gZ.busy) {
    return;
  }
  if (!gDisplayOk || !gBacklight) {
    __sync_synchronize();
    gZ.busy = false;
    return;
  }
  frame = gZ.curr;
  for (y = 0; y < LCD_HEIGHT; ++y) {
    int x0 = 0;
    int x1 = 0;
    int w;
    int i;
    const uint32_t *row66;
    uint8_t rgba_row[LCD_WIDTH * 4];
    if (!uimk2_zlist_row_dirty(&gZ, (uint16_t)y)) {
      continue;
    }
    if (!bezel_span(y, &x0, &x1)) {
      continue;
    }
    w = x1 - x0 + 1;
    row66 = (const uint32_t *)(const void *)(frame +
            ((size_t)y * (size_t)PANEL_W + (size_t)x0) * 4u);
    for (i = 0; i < w; ++i) {
      uimk2_blit_unpack66(row66[i], rgba_row + (size_t)i * 4u);
    }
    panel_push_rgba_span(x0, y, w, rgba_row);
    rows++;
    if ((y & 31) == 0) {
      delay(0);
    }
  }
  if (rows > 0) {
    Serial.printf("push rows %d\n", rows);
  }
  __sync_synchronize();
  gZ.busy = false;
}

static void core_b_task(void *arg) {
  (void)arg;
  Serial.println("core B up");
  player_http_boot();
  for (;;) {
    uint32_t now = millis();
    uint32_t wait;
    xSemaphoreTake(gMu, portMAX_DELAY);
    wait = uimk2_host_run(&gHost, now);
    xSemaphoreGive(gMu);
    for (;;) {
      bool have;
      bool stepped;
      uint8_t sel = (uint8_t)UIMK2_EV_NONE;
      int desired_before = 0;
      int desired_after = 0;
      bool more_volume = false;
      xSemaphoreTake(gMu, portMAX_DELAY);
      have = uimk2_ring_peek(&gRing) != nullptr;
      xSemaphoreGive(gMu);
      if (!have) {
        break;
      }
      paint_follow();
      xSemaphoreTake(gMu, portMAX_DELAY);
      {
        const uimk2_event *ev = uimk2_ring_peek(&gRing);
        if (ev != nullptr) {
          sel = ev->selector;
        }
        desired_before = gHost.desired;
        stepped = uimk2_host_step(&gHost, now);
        desired_after = gHost.desired;
        gBacklight = gHost.backlight;
        if (sel == (uint8_t)UIMK2_EV_VOLUME) {
          const uimk2_event *next = uimk2_ring_peek(&gRing);
          more_volume =
              next != nullptr && next->selector == (uint8_t)UIMK2_EV_VOLUME;
        }
      }
      xSemaphoreGive(gMu);
      if (!stepped) {
        break;
      }
      /* Queue only -- never block on sockets here. */
      if (sel == (uint8_t)UIMK2_EV_PLAYER_POLL) {
        if (!player_http_request_getstate()) {
          Serial.println("player poll skipped: WIFI_SSID empty");
        }
      } else if (sel == (uint8_t)UIMK2_EV_TOGGLE) {
        paint_follow();
        if (!player_http_request_toggle()) {
          Serial.println("player toggle skipped: WIFI_SSID empty");
        } else {
          Serial.println("player toggle queued");
        }
      } else if (sel == (uint8_t)UIMK2_EV_VOLUME) {
        if (desired_after != desired_before) {
          gVolumeSent = true;
          if (!more_volume) {
            if (!player_http_request_volume(desired_after)) {
              Serial.printf("player volume skipped: WIFI_SSID empty (%d)\n",
                            desired_after);
            } else {
              Serial.printf("player volume queued %d\n", desired_after);
            }
          }
        }
      }
    }
    pump_player_http();
    if (player_http_busy()) {
      /* Keep waking while a socket op is in flight. */
      wait = 0u;
    }
    if (wait == 0u) {
      taskYIELD();
    } else {
      uint32_t slice = wait;
      if (slice > 50u) {
        slice = 50u;
      }
      (void)ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(slice));
    }
  }
}

static void IRAM_ATTR on_encoder(void) {
  const uint32_t now = static_cast<uint32_t>(esp_timer_get_time());
  const uint8_t prev = gEncLast;
  const uint8_t cur =
      (static_cast<uint8_t>(gpio_get_level(static_cast<gpio_num_t>(PIN_ENC_A)))
       << 1) |
      static_cast<uint8_t>(gpio_get_level(static_cast<gpio_num_t>(PIN_ENC_B)));
  int8_t step = 0;
  gEncLast = cur;
  encoder_on_edge(prev, cur, now, &gClickPin, &gClickLockUs, &gClickHighUs,
                  &gRotation, &step);
  (void)step;
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
  if (*x < LCD_WIDTH) {
    *x = static_cast<uint16_t>(LCD_WIDTH - 1 - *x);
  }
  if (*y < LCD_HEIGHT) {
    *y = static_cast<uint16_t>(LCD_HEIGHT - 1 - *y);
  }
  return true;
}

static void take_rotation(void) {
  const int rot = gRotation;
  const int delta = rot - gTakenRot;
  bool woke = false;
  int shown = 0;
  gTakenRot = rot;
  if (delta == 0 || gMu == nullptr) {
    return;
  }
  xSemaphoreTake(gMu, portMAX_DELAY);
  gDesiredA = clamp_volume(gDesiredA + delta);
  shown = gDesiredA;
  woke = !gBacklight;
  wake_locked();
  (void)uimk2_post_volume(&gRing, shown);
  xSemaphoreGive(gMu);
  notify_b();
  Serial.printf("vol %d%s\n", shown, woke ? " wake" : "");
}

static void take_touch(void) {
  uint16_t x = 0;
  uint16_t y = 0;
  static bool was = false;
  const bool pressed = touch_pressed(&x, &y);
  bool woke = false;
  if (gMu == nullptr) {
    was = pressed;
    return;
  }
  if (pressed && !was) {
    xSemaphoreTake(gMu, portMAX_DELAY);
    woke = !gBacklight;
    if (woke) {
      /* A dark tap lights the glass. It does not hit-test, so it cannot
       * toggle transport by accident. */
      wake_locked();
    } else {
      (void)uimk2_post_press(&gRing, (int)x, (int)y);
    }
    xSemaphoreGive(gMu);
    notify_b();
    Serial.printf("touch %u %u%s\n", x, y, woke ? " wake" : "");
  }
  was = pressed;
}

static void apply_backlight(void) {
  bool lit = true;
  if (gMu == nullptr) {
    return;
  }
  xSemaphoreTake(gMu, portMAX_DELAY);
  lit = gBacklight;
  xSemaphoreGive(gMu);
  digitalWrite(PIN_LCD_BL, lit ? HIGH : LOW);
}

static void service_query(void) {
  static char buf[8];
  static size_t n = 0;
  while (Serial.available() > 0) {
    const int c = Serial.read();
    int desired = 0;
    int polled = 0;
    int polls = 0;
    int playing = 0;
    int lit = 0;
    if (c < 0) {
      return;
    }
    if (c != '\n' && c != '\r') {
      if (n + 1 < sizeof(buf)) {
        buf[n++] = static_cast<char>(c);
      } else {
        n = 0;
      }
      continue;
    }
    buf[n] = '\0';
    n = 0;
    if (strcmp(buf, "query") != 0) {
      continue;
    }
    xSemaphoreTake(gMu, portMAX_DELAY);
    desired = gHost.desired;
    polled = gPolled;
    polls = (int)gHost.polls;
    playing = gHost.playing ? 1 : 0;
    lit = gBacklight ? 1 : 0;
    xSemaphoreGive(gMu);
    Serial.printf("query backlight=%d playing=%d desired=%d polled=%d polls=%d "
                  "busy=%d\n",
                  lit, playing, desired, polled, polls, gZ.busy ? 1 : 0);
  }
}

static bool alloc_frames(void) {
  const size_t bytes = (size_t)UIMK2_FRAME_BYTES;
  gCurr = static_cast<uint8_t *>(
      heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  gNext = static_cast<uint8_t *>(
      heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (gCurr == nullptr || gNext == nullptr) {
    Serial.println("framebuffer alloc failed");
    return false;
  }
  memset(gCurr, 0, bytes);
  memset(gNext, 0, bytes);
  Serial.printf("framebuffer %u x2 psram\n", (unsigned)bytes);
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.printf("uimk2 follow: %s (%s)\n", BOARD_NAME, BOARD_SKU);
  pinMode(PIN_LCD_BL, OUTPUT);
  digitalWrite(PIN_LCD_BL, HIGH);
  gBacklight = true;

  gDisplayOk = panel_begin();
  Serial.printf("display begin %s\n", gDisplayOk ? "ok" : "fail");
  if (gDisplayOk) {
    panel_apply_waveshare_init();
    Serial.println("panel vendor init");
  }

  gMu = xSemaphoreCreateMutex();
  uimk2_ring_init(&gRing);
  uimk2_host_init(&gHost, &gRing, millis());
  gHost.desired = kBootVolume;
  if (alloc_frames()) {
    /* Before the worker starts, so the probe is not fighting Core B for
     * PSRAM. Frames are zeroed again for the follow view. */
    (void)bench_probe_short_title(gCurr, gNext);
    (void)bench_probe_blit(gCurr, gNext);
    memset(gCurr, 0, (size_t)UIMK2_FRAME_BYTES);
    memset(gNext, 0, (size_t)UIMK2_FRAME_BYTES);
    gBuilt = follow_glass_build(&gZ, gCurr, gNext, &gRing, ping_core_a, nullptr);
  }
  Serial.printf("zlist %s\n", gBuilt ? "ok" : "fail");
  if (gBuilt) {
    uimk2_host_bind(&gHost, &gZ);
    (void)uimk2_post_screen_on(&gRing);
    (void)uimk2_post_volume(&gRing, gDesiredA);
  }

  touch_init();
  encoder_begin();
  gUiTask = xTaskGetCurrentTaskHandle();
  /* HTTPClient on Core B needs more than the paint path. */
  xTaskCreatePinnedToCore(core_b_task, "uimk2", 32768, nullptr, 1, &gWorker, 0);
}

void loop() {
  take_rotation();
  take_touch();
  service_query();
  apply_backlight();
  if (ulTaskNotifyTake(pdTRUE, 0) > 0 || (gBuilt && gZ.busy)) {
    core_a_push();
  }
  delay(10);
}
