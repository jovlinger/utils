#include <Arduino.h>
#include "board_pins.h"

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("spinme scaffold: %s (%s)\n", BOARD_NAME, BOARD_SKU);
  Serial.printf("LCD %dx%d ST77916 QSPI; encoder pins TBD in board_pins.h\n",
                LCD_WIDTH, LCD_HEIGHT);
  pinMode(PIN_LCD_BL, OUTPUT);
  digitalWrite(PIN_LCD_BL, HIGH);
}

void loop() {
  static uint32_t last_ms = 0;
  uint32_t now = millis();
  if (now - last_ms >= 2000) {
    last_ms = now;
    Serial.println("heartbeat");
  }
}
