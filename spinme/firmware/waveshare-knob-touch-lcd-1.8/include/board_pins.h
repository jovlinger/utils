#pragma once

/* Waveshare ESP32-S3-Knob-Touch-LCD-1.8 -- S3-side pins.
 * Encoder A/B taken from the Waveshare 04_Encoder_Test sketch.
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

/* CST816S. SDA/SCL/INT/RST match the factory firmware pin tables. */
#define PIN_TOUCH_SDA 11
#define PIN_TOUCH_SCL 12
#define PIN_TOUCH_INT 9
#define PIN_TOUCH_RST 10
#define TOUCH_I2C_ADDR 0x15

/* Encoder from Waveshare 04_Encoder_Test: A=GPIO8, B=GPIO7, no switch. */
#define PIN_ENC_A 8
#define PIN_ENC_B 7
#define PIN_ENC_SW (-1)
