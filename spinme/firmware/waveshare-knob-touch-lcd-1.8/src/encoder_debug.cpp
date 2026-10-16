/* Display-free encoder trace. Built only by env encoder_debug.
 * One click is the first pin to change after the chatter lock.
 * GPIO8 = +1, GPIO7 = -1. The same pin can repeat during a fast spin.
 * No LCD, touch, or WiFi.
 */
#include <Arduino.h>
#include <driver/gpio.h>
#include <esp_timer.h>

#include "board_pins.h"
#include "encoder_decode.h"

static volatile int gRotation = 0;
static volatile uint8_t gEncLast = 0;
static volatile uint8_t gClickPin = 0;
static volatile uint32_t gClickLockUs = 0;
static volatile uint32_t gClickHighUs = 0;

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

static void IRAM_ATTR on_encoder(void) {
  const uint8_t prev = gEncLast;
  const uint8_t cur =
      (static_cast<uint8_t>(gpio_get_level(static_cast<gpio_num_t>(PIN_ENC_A)))
       << 1) |
      static_cast<uint8_t>(gpio_get_level(static_cast<gpio_num_t>(PIN_ENC_B)));
  gEncLast = cur;
  const uint32_t now = static_cast<uint32_t>(esp_timer_get_time());
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

void setup(void) {
  Serial.begin(115200);
  delay(200);
  Serial.println("encoder-debug");
  Serial.println("ab=(A<<1)|B A=GPIO8=+1 B=GPIO7=-1 lock=200ms");
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

void loop(void) {
  drain_enc_log();
  static uint32_t last_ms = 0;
  const uint32_t now = millis();
  if (now - last_ms >= 1000) {
    last_ms = now;
    Serial.printf("rot %d\n", (int)gRotation);
  }
  delay(2);
}
