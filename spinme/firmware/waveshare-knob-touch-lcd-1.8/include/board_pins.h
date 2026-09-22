#pragma once

/* Waveshare ESP32-S3-Knob-Touch-LCD-1.8 -- S3-side pins from research notes.
 * Confirm against schematic / 04_Encoder_Test before trusting encoder GPIOs.
 */

#define BOARD_SKU "WS-ESP32-S3-Knob-Touch-LCD-1.8"
#define BOARD_NAME "Waveshare-Knob-Touch-LCD-1.8"

/* ST77916 QSPI display (Arduino demo pins, S3) */
#define PIN_LCD_CS 14
#define PIN_LCD_PCLK 13
#define PIN_LCD_DATA0 15
#define PIN_LCD_DATA1 16
#define PIN_LCD_DATA2 17
#define PIN_LCD_DATA3 18
#define PIN_LCD_RST 21
#define PIN_LCD_BL 47
#define LCD_WIDTH 360
#define LCD_HEIGHT 360

/* CST816 touch -- exact I2C pins: confirm from wiki/schematic */
/* Encoder GPIOs: confirm from schematic / 04_Encoder_Test */

#define PIN_ENC_A (-1)
#define PIN_ENC_B (-1)
#define PIN_ENC_SW (-1)
