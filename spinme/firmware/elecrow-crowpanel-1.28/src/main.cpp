#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include "board_pins.h"

#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASS
#define WIFI_PASS ""
#endif
#ifndef VOLUMIO_HOST
#define VOLUMIO_HOST "miniDSP-SHD.local"
#endif

static bool wifi_ok = false;

static bool ensure_wifi(void) {
  if (WIFI_SSID[0] == '\0') {
    Serial.println("WIFI_SSID empty; set build_flags -DWIFI_SSID=... -DWIFI_PASS=...");
    return false;
  }
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }
  Serial.printf("WiFi connecting to %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  const uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(250);
    Serial.print('.');
  }
  Serial.println();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi failed");
    return false;
  }
  Serial.print("WiFi OK ");
  Serial.println(WiFi.localIP());
  return true;
}

static void volumio_get(const char *path) {
  HTTPClient http;
  String url = String("http://") + VOLUMIO_HOST + path;
  Serial.printf("GET %s\n", url.c_str());
  if (!http.begin(url)) {
    Serial.println("http.begin failed");
    return;
  }
  const int code = http.GET();
  Serial.printf("HTTP %d\n", code);
  if (code > 0) {
    Serial.println(http.getString().substring(0, 400));
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("spinme: %s (%s) host=%s\n", BOARD_NAME, BOARD_SKU, VOLUMIO_HOST);
  pinMode(PIN_LCD_BL, OUTPUT);
  digitalWrite(PIN_LCD_BL, HIGH);
  pinMode(PIN_ENC_SW, INPUT_PULLUP);
  wifi_ok = ensure_wifi();
  if (wifi_ok) {
    volumio_get("/api/v1/getState");
  }
}

void loop() {
  static int last_sw = HIGH;
  const int sw = digitalRead(PIN_ENC_SW);
  if (last_sw == HIGH && sw == LOW) {
    if (ensure_wifi()) {
      volumio_get("/api/v1/commands/?cmd=volume&volume=plus");
      delay(50);
      volumio_get("/api/v1/getState");
    }
  }
  last_sw = sw;
  delay(10);
}
