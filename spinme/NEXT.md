# Display streaks -- try in order

Scratch list. Check a box only after looking at the glass.
This file is on the main checkout so `git reset --hard checkpoint`
in the device-ui worktree does not erase it.

Source thread (read 2026-10-13): Sunton ESP32-8048S070C, 800x480 RGB,
driver EK9716, LVGL 9 + Arduino_GFX. Symptom there is a periodic
full-screen flash, not our static columns.

https://forum.lvgl.io/t/periodic-full-screen-flicker-on-esp32-s3-rgb-display-lvgl-9-arduino-gfx-arduino-ide-that-survives-buffer-timing-touch-tweaks-suspect-only-esp-idfs-avoid-tearing-flag-fixes-it/24340

Our glass: Waveshare ESP32-S3-Knob-Touch-LCD-1.8, ST77916, QSPI on
SPI2, 360x360. Revert point: tag `checkpoint` (`sha:10d35c6`).
Framework in the flashed experiment: Arduino core 2.0.17, our
`panel_io` SPI driver. Not Arduino_GFX, LovyanGFX, MicroPython, or
the ESP-IDF RGB LCD driver.

## Try

- [x] Black fill (flashed, uncommitted). Pinstripes remain, extremely
      faint. Score 9/10. Acceptable if nothing later beats it.
      Glyph layout is not the cause.
- [x] Backlight low for the whole reset and vendor init, then high.
      Score 10/10. Zero pinstripes. Winner so far.
      The scored change is BL low before init and BL high after vendor
      init. Yellow "TOP" was only a marker so a blank glass was obvious.
      Community note is from 1.28 inch round boards: drive TFT_BL high,
      and toggle the display power line off during init before turning
      it back on. On this 1.8 knob, BL is GPIO 47 and setup already
      drives it high and leaves it high. RST is GPIO 21 (low 10 ms,
      high, wait 150 ms) and there is no third power pin. The untried
      part is BL low until after DISPON.
- [x] One pixel transaction for the whole frame. Score 10/10.
      FLASHED on checkpoint (status text, backlight high during init).
      DMA max is 32768 bytes, so a 259200-byte frame cannot be one burst.
      This build used 8 chunks of 45 rows under one RAMWR with CS held
      (was 16-row chunks).
      Gemini's "DMA desync" wording: a dropped clock mid-transfer offsets
      the data by one pixel on every other column. That is this test,
      plus the cache-line measurement below. The pixel buffer is internal
      RAM (`gBand`), sent with SPI DMA.
- [x] QSPI clock 40 MHz, then 20, then 10. Both 20 MHz and 10 MHz
      score 8/10: no pinstripe, same flicker, and the flicker is worse
      than the pinstripe. Checkpoint otherwise (16-row chunks, backlight
      high during init).
- [x] Print `CONFIG_ESP32S3_DATA_CACHE_LINE_SIZE` and whether the pixel
      buffer is internal RAM. Measured, no glass change. The `qio_opi`
      sdkconfig is line size 32 and `CONFIG_SPIRAM_MODE_OCT`. `gBand` is
      a static BSS array, not a PSRAM allocation. Core not rebuilt.
      https://github.com/espressif/arduino-esp32/issues/12480
- [x] Draw the frame once, after WiFi is idle. Score 10/10.
      The first flash froze on the pre-connect "wifi ..." line. The scored
      flash stays blank until the attempt finishes, then draws once.
      https://github.com/espressif/esp-faq/blob/fad305a/docs/en/software-framework/peripherals/lcd.rst
      If a settled black frame is still striped, that stall is not it.
- [x] Flash Waveshare `08_LVGL_Test` unchanged. Skipped 2026-10-13:
      no `idf.py`, and the demo is ESP-IDF 5.3.2. Sensing touch and
      rotation instead.

## Do not try (links from that thread, other hardware)

These are the RGB LCD peripheral on the Sunton 7 inch. Our panel has
no hsync, vsync, or DE.

- [x] Skip hsync/vsync porch copy, including Gemini's ST7701S HBP/HFP/HSYNC
      "driver sync" fix. That pattern is for round RGB panels. This glass
      is ST77916 on QSPI and has no porch registers.
      https://github.com/halyssonJr/lvgl-demo-esp32s3/blob/79e862ca332525ba8721c4691f450fb44ec08738/main/lcd_display.h
      Lines 90-106 are 800x480 timings, PCLK 18 MHz.
- [x] Skip `avoid_tearing`, bounce buffer, and RGB "screen drift" restart.
      IDF 5.1 fixes that for the RGB controller. We are on Arduino
      2.0.17 (IDF 4.4) and a QSPI panel.
      https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/lcd/rgb_lcd.html
- [x] Skip moving touch to the other core. The thread did that and the
      flash remained.
      https://forum.lvgl.io/t/display-esp32-esp32-8048s043-screen-shake/24253/2
- [x] Skip LovyanGFX. The thread switched to it, got worse color sync,
      and reverted.
- [x] Skip the other poster's PSRAM sdkconfig as a first step. Their
      bug was a wrong PSRAM mode on an RGB framebuffer in PSRAM.
      https://forum.lvgl.io/t/using-lvgl-without-esp-lvgl-port/24328
      Useful only if item "print cache line" shows the pixel buffer
      is in PSRAM.

## Earlier notes

- focus on volume io basic start stop, ratchet
- write a todo for each basic functionality, under umbrella todo

## Diff against checkpoint (backlight 10/10)

`git diff checkpoint` on `4a26154c-device-ui` before reset.
The backlight lines are the winner. The `draw_status` hunk is the
TOP marker, not the stripe fix.

```
diff --git a/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/main.cpp b/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/main.cpp
index 63b6157..3857103 100644
--- a/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/main.cpp
+++ b/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/main.cpp
@@ -105,33 +105,8 @@ static void draw_status(void) {
     return;
   }
   panel_fill_screen(0x0000);
-  const int line_h = kGlyphH * kTextSize;
-  char volume[16];
-  snprintf(volume, sizeof(volume), "vol %d", gVolume);
-  const char *texts[kLineCount] = {
-      gAwake ? "spinme" : "asleep",
-      gStatus,
-      gArtist,
-      gTitle,
-      volume,
-      gActivity,
-  };
-  const uint16_t colors[kLineCount] = {kYellow, kWhite, kWhite, kWhite, kWhite, kWhite};
-  const char *shown[kLineCount];
-  uint16_t shown_colors[kLineCount];
-  int count = 0;
-  for (int i = 0; i < kLineCount; ++i) {
-    if (texts[i][0] == '\0') {
-      continue;
-    }
-    shown[count] = texts[i];
-    shown_colors[count] = colors[i];
-    count++;
-  }
-  const int y0 = (LCD_HEIGHT - count * line_h) / 2;
-  for (int i = 0; i < count; ++i) {
-    draw_centered(shown[i], y0 + i * line_h, shown_colors[i]);
-  }
+  /* Top third, left of center, so a blank glass is obvious. */
+  panel_text(80, 48, "TOP", kTextSize, 0xFFE0);
 }
 
 static void wake_display(void) {
@@ -336,7 +311,7 @@ void setup() {
   Serial.printf("spinme: %s (%s)\n", BOARD_NAME, BOARD_SKU);
 
   pinMode(PIN_LCD_BL, OUTPUT);
-  digitalWrite(PIN_LCD_BL, HIGH);
+  digitalWrite(PIN_LCD_BL, LOW);
   gLastActivityMs = millis();
 
   gDisplayOk = panel_begin();
@@ -344,6 +319,7 @@ void setup() {
   if (gDisplayOk) {
     panel_apply_waveshare_init();
     Serial.println("panel vendor init");
+    digitalWrite(PIN_LCD_BL, HIGH);
     draw_status();
   }
 
```

## Diff against checkpoint (45-row DMA, 10/10)

`git diff checkpoint` on `4a26154c-device-ui` before the next reset.

```
diff --git a/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/panel_io.cpp b/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/panel_io.cpp
index 85602cc..8621494 100644
--- a/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/panel_io.cpp
+++ b/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/panel_io.cpp
@@ -11,7 +11,12 @@
 #include "glcd5x7.h"
 
 static const int kClockHz = 40 * 1000 * 1000;
-static const int kBandRows = 16;
+/* SPI DMA on this core accepts at most 32768 bytes per transaction
+ * (SPI_LL_DMA_MAX_BIT_LEN is 18 bits). 45 rows is the largest whole-row
+ * chunk under that cap, and 360/45 is 8, so a full frame is 8 DMA
+ * bursts under one RAMWR with CS held. A literal 259200-byte transaction
+ * does not fit. */
+static const int kBandRows = 45;
 
 static const char *kTag = "panel";
 static spi_device_handle_t gDev = nullptr;
```

## Diff against checkpoint (20 MHz, 8/10)

`git diff checkpoint` on `4a26154c-device-ui` before the next reset.
No pinstripe. Flicker is worse than the pinstripe.

```
diff --git a/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/panel_io.cpp b/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/panel_io.cpp
index 85602cc..169d579 100644
--- a/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/panel_io.cpp
+++ b/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/panel_io.cpp
@@ -10,7 +10,7 @@
 #include "board_pins.h"
 #include "glcd5x7.h"
 
-static const int kClockHz = 40 * 1000 * 1000;
+static const int kClockHz = 20 * 1000 * 1000;
 static const int kBandRows = 16;
 
 static const char *kTag = "panel";
```

## Diff against checkpoint (10 MHz, 8/10)

`git diff checkpoint` on `4a26154c-device-ui` before the next reset.
Same flicker as 20 MHz. No pinstripe.

```
diff --git a/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/panel_io.cpp b/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/panel_io.cpp
index 85602cc..1fb73ff 100644
--- a/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/panel_io.cpp
+++ b/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/panel_io.cpp
@@ -10,7 +10,7 @@
 #include "board_pins.h"
 #include "glcd5x7.h"
 
-static const int kClockHz = 40 * 1000 * 1000;
+static const int kClockHz = 10 * 1000 * 1000;
 static const int kBandRows = 16;
 
 static const char *kTag = "panel";
```

## Diff against checkpoint (draw after WiFi, 10/10)

`git diff checkpoint` on `4a26154c-device-ui` before reset.
The scored flash does not draw the pre-connect "wifi ..." line.

```
diff --git a/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/main.cpp b/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/main.cpp
index 63b6157..8c7eb29 100644
--- a/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/main.cpp
+++ b/spinme/firmware/waveshare-knob-touch-lcd-1.8/src/main.cpp
@@ -100,10 +100,13 @@ static void draw_centered(const char *text, int y, uint16_t color) {
   panel_text(x, y, buf, kTextSize, color);
 }
 
+static bool gFrameSent = false;
+
 static void draw_status(void) {
-  if (!gDisplayOk) {
+  if (!gDisplayOk || gFrameSent) {
     return;
   }
+  gFrameSent = true;
   panel_fill_screen(0x0000);
   const int line_h = kGlyphH * kTextSize;
   char volume[16];
@@ -245,7 +248,6 @@ static void connect_wifi(void) {
     return;
   }
   copy_text(gStatus, sizeof(gStatus), "wifi ...");
-  draw_status();
   WiFi.mode(WIFI_STA);
   WiFi.setSleep(false);
   WiFi.begin(SPINME_WIFI_SSID, SPINME_WIFI_PASS);
@@ -261,6 +263,7 @@ static void connect_wifi(void) {
     Serial.println("wifi fail");
     copy_text(gStatus, sizeof(gStatus), "wifi fail");
   }
+  delay(500);
   draw_status();
 }
 
@@ -344,7 +347,6 @@ void setup() {
   if (gDisplayOk) {
     panel_apply_waveshare_init();
     Serial.println("panel vendor init");
-    draw_status();
   }
 
   touch_init();
```
