#include <Arduino.h>
#include "board_pins.h"

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("spinme scaffold: %s (%s)\n", BOARD_NAME, BOARD_SKU);
  Serial.printf("LCD %dx%d GC9A01 SPI; encoder A/B/SW=%d/%d/%d\n", LCD_WIDTH,
                LCD_HEIGHT, PIN_ENC_A, PIN_ENC_B, PIN_ENC_SW);
  pinMode(PIN_LCD_BL, OUTPUT);
  digitalWrite(PIN_LCD_BL, HIGH);
  pinMode(PIN_ENC_SW, INPUT_PULLUP);
}

void loop() {
  static uint32_t last_ms = 0;
  uint32_t now = millis();
  if (now - last_ms >= 2000) {
    last_ms = now;
    Serial.printf("heartbeat sw=%d\n", digitalRead(PIN_ENC_SW) == LOW);
  }
}
