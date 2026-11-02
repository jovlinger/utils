/*
 * spinme TaskActor fabric on the Waveshare knob (S3).
 *
 * Draw is the sole glass owner. Touch and rotary reach it only through ISR
 * mail (FromISR ring, no task mutex); Draw hit-tests and posts ControlEvents
 * to the Controller Router; MPDController drives Net (player_http); Net
 * completions and status flow back as events. The Draw task is also the
 * single fabric runner for now: it pumps Draw's queue, ticks the Scheduler,
 * and pumps the non-blocking player_http socket (Net's own task comes with
 * the 1:1 split once stacks are measured -- see PLAN scheduling).
 *
 * Core A (Arduino loop) only samples the CST816 over I2C (I2C cannot run in
 * the INT ISR) and posts presses into the touch mail, plus the serial
 * "query" line.
 */
#include <Arduino.h>
#include <Wire.h>
#include <driver/gpio.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <stdlib.h>
#include <string.h>

#include "board_pins.h"
#include "encoder_decode.h"
#include "panel_init.h"
#include "panel_io.h"
#include "player_http.h"
#include "rom_jpeg.h"
#include "ta_controller.h"
#include "ta_device_boot.h"
#include "ta_draw_events.h"
#include "ta_draw_glass.h"
#include "ta_event.h"
#include "ta_glass_device.h"
#include "ta_input_isr.h"
#include "ta_isr_mail.h"
#include "ta_net_backend.h"
#include "ta_net_events.h"
#include "ta_net_player_bind.h"
#include "ta_registry.h"
#include "ta_router.h"

/* ISR -> Draw only. Two single-producer mails: the encoder ISR and the
 * touch sampler (Core A task context) never share a tail. */
static ta_isr_mail_t gMailRotary;
static ta_isr_mail_t gMailTouch;
static TaskHandle_t gDrawTask = nullptr;
static bool gDisplayOk = false;
static bool gGlassBound = false;

static volatile uint8_t gEncLast = 0;
static volatile uint8_t gClickPin = 0;
static volatile uint32_t gClickLockUs = 0;
static volatile uint32_t gClickHighUs = 0;
static volatile int gRotation = 0;

static void notify_draw(void) {
  if (gDrawTask != nullptr) {
    xTaskNotifyGive(gDrawTask);
  }
}

/* ---- albumart decode glue (000b moves this behind Net/Draw artwork) ---- */

static volatile bool gDecodeBusy = false;

struct DecodeJob {
  uint8_t *jpeg;
  size_t nbytes;
};

static void post_base_dirty(void) {
  ta_event_t ev;
  uint8_t pl[1] = {TA_DRAW_UPD_BASE_DIRTY};
  ta_event_clear(&ev);
  ev.type = TA_EV_DRAW_UPDATE;
  ev.session_id = 1;
  (void)ta_event_set_src(&ev, "albumart");
  (void)ta_event_set_payload(&ev, pl, 1);
  (void)ta_registry_post(TA_DRAW_NAME, &ev); /* MP/SC queue push */
  notify_draw();
}

static void albumart_decode_task(void *arg) {
  DecodeJob *job = static_cast<DecodeJob *>(arg);
  uint8_t *rgba = ta_glass_device_rgba_scratch();
  RomJpegInfo ji;
  if (job == nullptr) {
    gDecodeBusy = false;
    vTaskDelete(nullptr);
    return;
  }
  if (rgba == nullptr) {
    Serial.println("albumart scratch null");
  } else if (!rom_jpeg_decode_nn_rgba(job->jpeg, job->nbytes, rgba,
                                      (uint16_t)LCD_WIDTH, (uint16_t)LCD_HEIGHT,
                                      &ji)) {
    Serial.printf("albumart romjpeg fail prep=%d decomp=%d ms=%u\n",
                  ji.jd_prepare, ji.jd_decomp, (unsigned)ji.decode_ms);
  } else {
    ta_glass_device_base_from_rgba(rgba);
    post_base_dirty();
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
  vTaskDelete(nullptr);
}

static void on_albumart_ok(void) {
  uint8_t *jpeg = nullptr;
  size_t nbytes = 0;
  uint32_t fetch_ms = 0;
  DecodeJob *job;
  if (!player_http_take_albumart(&jpeg, &nbytes, &fetch_ms)) {
    return;
  }
  Serial.printf("albumart fetch %u bytes %u ms\n", (unsigned)nbytes,
                (unsigned)fetch_ms);
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

/* Net wire pump: completions become Net DONE events (and text/status). */
static void pump_player_http(void) {
  PlayerHttpEvent ev = player_http_tick();
  if (ev != PLAYER_HTTP_EV_NONE) {
    ta_net_on_player_http_event((int)ev);
  }
  if (ev == PLAYER_HTTP_EV_GETSTATE_FAIL) {
    Serial.println("player poll fail");
  } else if (ev == PLAYER_HTTP_EV_ALBUMART_OK) {
    on_albumart_ok();
  } else if (ev == PLAYER_HTTP_EV_ALBUMART_FAIL) {
    Serial.println("albumart fetch fail");
  } else if (ev == PLAYER_HTTP_EV_CMD_FAIL) {
    Serial.println("player cmd fail");
  } else if (ev == PLAYER_HTTP_EV_CMD_OK) {
    Serial.println("player cmd ok (net)");
  }
}

/* ---- Draw task: glass owner + fabric runner ---------------------------- */

static void draw_task(void *arg) {
  (void)arg;
  ta_isr_mail_t *mails[2] = {&gMailRotary, &gMailTouch};
  Serial.println("draw task up");
  player_http_boot();
  ta_net_bind_player_http();
  for (;;) {
    size_t handled = ta_draw_pump(mails, 2);
    /* Scheduler real time: this task is the only fabric runner. */
    ta_device_tick_ms(millis());
    pump_player_http();
    handled += ta_draw_pump(mails, 2);
    if (handled > 0) {
      const ta_draw_stats_t *ds = ta_draw_stats();
      static unsigned last_drops = 0;
      if (ds->isr_drops != last_drops) {
        last_drops = ds->isr_drops;
        Serial.printf("ERROR: ISR mail drops %u\n", last_drops);
      }
    }
    if (player_http_busy()) {
      taskYIELD();
    } else {
      (void)ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(20));
    }
  }
}

/* ---- input edges -------------------------------------------------------- */

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
  if (step != 0) {
    BaseType_t woken = pdFALSE;
    (void)ta_isr_post_rotary(&gMailRotary, step, 0);
    if (gDrawTask != nullptr) {
      vTaskNotifyGiveFromISR(gDrawTask, &woken);
      portYIELD_FROM_ISR(woken);
    }
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

/* Press edge -> touch mail -> Draw. No hit-test here; Draw owns it. */
static void take_touch(void) {
  uint16_t x = 0;
  uint16_t y = 0;
  static bool was = false;
  const bool pressed = touch_pressed(&x, &y);
  if (pressed && !was) {
    (void)ta_isr_post_touch(&gMailTouch, x, y);
    notify_draw();
    Serial.printf("touch %u %u\n", x, y);
  }
  was = pressed;
}

/* Serial: "query" dumps counters; "tap X Y" / "rot N" inject into the same
 * mails the sampler/ISR use (bench smoke without hands on the knob). */
static void service_query(void) {
  static char buf[24];
  static size_t n = 0;
  while (Serial.available() > 0) {
    const int c = Serial.read();
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
    if (strncmp(buf, "tap ", 4) == 0) {
      const int x = atoi(buf + 4);
      const char *sp = strchr(buf + 4, ' ');
      const int y = sp != nullptr ? atoi(sp + 1) : 0;
      (void)ta_isr_post_touch(&gMailTouch, (uint16_t)x, (uint16_t)y);
      notify_draw();
      Serial.printf("tap inject %d %d\n", x, y);
      continue;
    }
    if (strncmp(buf, "rot ", 4) == 0) {
      const int steps = atoi(buf + 4);
      (void)ta_isr_post_rotary(&gMailRotary, (int8_t)steps, 0);
      notify_draw();
      Serial.printf("rot inject %d\n", steps);
      continue;
    }
    if (strcmp(buf, "query") != 0) {
      continue;
    }
    {
      const ta_glass_stats_t *gs = ta_glass_stats();
      const ta_draw_stats_t *ds = ta_draw_stats();
      const ta_controller_stats_t *ms = ta_mpd_stats();
      Serial.printf("query backlight=%d playing=%d desired=%d polled=%d "
                    "polls=%u installed=%d pushes=%u hits=%u isr=%u drops=%u "
                    "toggles=%u title=\"%s\"\n",
                    ta_glass_backlight(), ta_glass_playing(),
                    ta_glass_desired(), ta_glass_polled(), ms->poll_done,
                    ta_glass_installed(), gs->pushes, gs->hits,
                    ds->isr_drained, ds->isr_drops, ms->toggle,
                    ta_glass_text(TA_DRAW_TEXT_TITLE));
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.printf("spinme fabric: %s (%s)\n", BOARD_NAME, BOARD_SKU);
  pinMode(PIN_LCD_BL, OUTPUT);
  digitalWrite(PIN_LCD_BL, HIGH);

  gDisplayOk = panel_begin();
  Serial.printf("display begin %s\n", gDisplayOk ? "ok" : "fail");
  if (gDisplayOk) {
    panel_apply_waveshare_init();
    Serial.println("panel vendor init");
  }

  ta_isr_mail_reset(&gMailRotary);
  ta_isr_mail_reset(&gMailTouch);
  /* Boot the fabric: Draw's queue is bound inside, so the activation's
   * DRAW_SET_SHAPE_STACK waits until the glass glue below is in place and
   * the Draw task pumps it. */
  ta_device_boot();
  Serial.printf("ta fabric_up=%d\n", ta_device_fabric_up());
  gGlassBound = ta_glass_device_bind();
  Serial.printf("glass %s\n", gGlassBound ? "ok" : "fail");

  touch_init();
  encoder_begin();
  Serial.printf("ta fabric_up=%d (post-init)\n", ta_device_fabric_up());
  xTaskCreatePinnedToCore(draw_task, "ta_draw", 32768, nullptr, 1, &gDrawTask,
                          0);
}

void loop() {
  take_touch();
  service_query();
  delay(10);
}
