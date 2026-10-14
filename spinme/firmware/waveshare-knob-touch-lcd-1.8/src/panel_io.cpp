#include "panel_io.h"

#include <string.h>

#include <driver/gpio.h>
#include <driver/spi_master.h>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>

#include "board_pins.h"
#include "glcd5x7.h"

static const int kClockHz = 40 * 1000 * 1000;
static const int kBandRows = 16;

static const char *kTag = "panel";
static spi_device_handle_t gDev = nullptr;
static bool gTxLogged = false;
alignas(4) static uint16_t gBand[LCD_WIDTH * kBandRows];

static uint16_t swap16(uint16_t color) {
  return (uint16_t)((color << 8) | (color >> 8));
}

static void tx(const uint8_t *bytes, size_t len, uint32_t flags) {
  spi_transaction_t trans;
  memset(&trans, 0, sizeof(trans));
  trans.length = len * 8;
  trans.tx_buffer = bytes;
  trans.flags = flags;
  const esp_err_t err = spi_device_polling_transmit(gDev, &trans);
  if (err != ESP_OK && !gTxLogged) {
    gTxLogged = true;
    ESP_LOGE(kTag, "spi tx %d flags %u len %u", (int)err, (unsigned)flags,
             (unsigned)len);
  }
}

/* Waveshare esp_lcd path: 32-bit command word in 1-bit mode, pixel bytes in 4-bit mode.
 * The word is sent as a buffer, wire order 0xOP, 0x00, reg, 0x00.
 */
static void tx_word(uint8_t opcode, uint8_t reg, const uint8_t *data, size_t len,
                    bool data_quad) {
  uint8_t word[4] = {opcode, 0x00, reg, 0x00};
  uint8_t scratch[16];
  const uint8_t *payload = data;
  if (data != nullptr && len > 0) {
    if (len > sizeof(scratch)) {
      len = sizeof(scratch);
    }
    memcpy(scratch, data, len);
    payload = scratch;
    tx(word, 4, SPI_TRANS_CS_KEEP_ACTIVE);
    tx(payload, len, data_quad ? SPI_TRANS_MODE_QIO : 0);
  } else {
    tx(word, 4, 0);
  }
}

void panel_cmd(uint8_t cmd, const uint8_t *data, size_t len) {
  tx_word(0x02, cmd, data, len, false);
}

static void set_window(int x, int y, int w, int h) {
  const int x1 = x + w - 1;
  const int y1 = y + h - 1;
  const uint8_t caset[4] = {
      (uint8_t)((x >> 8) & 0xff),
      (uint8_t)(x & 0xff),
      (uint8_t)((x1 >> 8) & 0xff),
      (uint8_t)(x1 & 0xff),
  };
  const uint8_t raset[4] = {
      (uint8_t)((y >> 8) & 0xff),
      (uint8_t)(y & 0xff),
      (uint8_t)((y1 >> 8) & 0xff),
      (uint8_t)(y1 & 0xff),
  };
  panel_cmd(0x2A, caset, 4);
  panel_cmd(0x2B, raset, 4);
}

static void write_pixels(const uint16_t *pixels, size_t count) {
  uint8_t word[4] = {0x32, 0x00, 0x2C, 0x00};
  const uint8_t *cursor = (const uint8_t *)pixels;
  size_t bytes = count * 2;
  tx(word, 4, SPI_TRANS_CS_KEEP_ACTIVE);
  while (bytes > 0) {
    size_t chunk = bytes;
    if (chunk > LCD_WIDTH * kBandRows * 2) {
      chunk = LCD_WIDTH * kBandRows * 2;
    }
    const uint32_t keep = (chunk < bytes) ? SPI_TRANS_CS_KEEP_ACTIVE : 0;
    tx(cursor, chunk, SPI_TRANS_MODE_QIO | keep);
    cursor += chunk;
    bytes -= chunk;
  }
}

bool panel_begin(void) {
  spi_bus_config_t buscfg;
  memset(&buscfg, 0, sizeof(buscfg));
  buscfg.mosi_io_num = PIN_LCD_DATA0;
  buscfg.miso_io_num = PIN_LCD_DATA1;
  buscfg.sclk_io_num = PIN_LCD_PCLK;
  buscfg.quadwp_io_num = PIN_LCD_DATA2;
  buscfg.quadhd_io_num = PIN_LCD_DATA3;
  buscfg.max_transfer_sz = LCD_WIDTH * kBandRows * 2 + 8;
  if (spi_bus_initialize(SPI2_HOST, &buscfg, SPI_DMA_CH_AUTO) != ESP_OK) {
    return false;
  }
  spi_device_interface_config_t devcfg;
  memset(&devcfg, 0, sizeof(devcfg));
  devcfg.flags = SPI_DEVICE_HALFDUPLEX;
  devcfg.clock_speed_hz = kClockHz;
  devcfg.mode = 0;
  devcfg.spics_io_num = PIN_LCD_CS;
  devcfg.queue_size = 1;
  if (spi_bus_add_device(SPI2_HOST, &devcfg, &gDev) != ESP_OK) {
    return false;
  }
  /* CS must stay asserted across the command word and the following data.
   * That flag is rejected unless this device already owns the bus. */
  if (spi_device_acquire_bus(gDev, portMAX_DELAY) != ESP_OK) {
    return false;
  }
  return true;
}

void panel_fill_screen(uint16_t color565) {
  const uint16_t swapped = swap16(color565);
  for (int i = 0; i < LCD_WIDTH * kBandRows; ++i) {
    gBand[i] = swapped;
  }
  set_window(0, 0, LCD_WIDTH, LCD_HEIGHT);
  uint8_t word[4] = {0x32, 0x00, 0x2C, 0x00};
  tx(word, 4, SPI_TRANS_CS_KEEP_ACTIVE);
  const size_t band_bytes = LCD_WIDTH * kBandRows * 2;
  size_t left = (size_t)LCD_WIDTH * LCD_HEIGHT * 2;
  while (left > 0) {
    size_t chunk = left < band_bytes ? left : band_bytes;
    const uint32_t keep = (chunk < left) ? SPI_TRANS_CS_KEEP_ACTIVE : 0;
    tx((const uint8_t *)gBand, chunk, SPI_TRANS_MODE_QIO | keep);
    left -= chunk;
  }
}

void panel_text(int x, int y, const char *s, int scale, uint16_t color565) {
  if (s == nullptr || s[0] == '\0' || scale < 1) {
    return;
  }
  const int row_h = 8 * scale;
  const uint16_t ink = swap16(color565);
  const uint16_t paper = swap16(0x0000);
  for (int i = 0; i < LCD_WIDTH * row_h; ++i) {
    gBand[i] = paper;
  }
  int cursor = x;
  for (const char *p = s; *p != '\0'; ++p) {
    const uint8_t code = (uint8_t)*p;
    const uint8_t *glyph = &kGlcd5x7[(size_t)code * 5];
    for (int col = 0; col < 5; ++col) {
      uint8_t bits = glyph[col];
      for (int row = 0; row < 8; ++row) {
        if ((bits & (1 << row)) == 0) {
          continue;
        }
        for (int sy = 0; sy < scale; ++sy) {
          const int py = row * scale + sy;
          if (py < 0 || py >= row_h) {
            continue;
          }
          for (int sx = 0; sx < scale; ++sx) {
            const int px = cursor + col * scale + sx;
            if (px < 0 || px >= LCD_WIDTH) {
              continue;
            }
            gBand[py * LCD_WIDTH + px] = ink;
          }
        }
      }
    }
    cursor += 6 * scale;
  }
  if (y < 0 || y + row_h > LCD_HEIGHT) {
    return;
  }
  set_window(0, y, LCD_WIDTH, row_h);
  write_pixels(gBand, (size_t)LCD_WIDTH * row_h);
}
