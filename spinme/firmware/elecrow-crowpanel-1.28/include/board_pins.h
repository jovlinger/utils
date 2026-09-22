#pragma once

/* Elecrow CrowPanel 1.28" rotary (DHE38128D) -- pins from Elecrow wiki. */

#define BOARD_SKU "DHE38128D"
#define BOARD_NAME "CrowPanel-1.28-rotary"

/* GC9A01 SPI display */
#define PIN_LCD_SCLK 10
#define PIN_LCD_MOSI 11
#define PIN_LCD_MISO (-1)
#define PIN_LCD_DC 3
#define PIN_LCD_CS 9
#define PIN_LCD_RST 14
#define PIN_LCD_BL 46
#define LCD_WIDTH 240
#define LCD_HEIGHT 240

/* CST816D touch I2C */
#define PIN_TP_SDA 6
#define PIN_TP_SCL 7
#define PIN_TP_INT 5
#define PIN_TP_RST 13

/* Rotary encoder */
#define PIN_ENC_A 45
#define PIN_ENC_B 42
#define PIN_ENC_SW 41

/* WS2812 ambient LEDs */
#define PIN_WS2812 48
#define WS2812_COUNT 5

#define PIN_POWER_LED 40
