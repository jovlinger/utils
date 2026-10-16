#include "panel_io.h"

#include <string.h>

#include <driver/gpio.h>
#include <driver/spi_master.h>
#include <esp_heap_caps.h>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>

#include "board_pins.h"
#include "glyph_file.h"
#include "layout_box.h"

static const int kClockHz = 40 * 1000 * 1000;
static const int kBandRows = 16;

static const char *kTag = "panel";
static spi_device_handle_t gDev = nullptr;
static bool gTxLogged = false;
alignas(4) static uint16_t gBand[LCD_WIDTH * kBandRows];
/* Host-order RGB565. gFront matches the glass. Draws write gBack. */
static uint16_t *gFront = nullptr;
static uint16_t *gBack = nullptr;
static bool gGlassSynced = false;

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
  glyph_file_mmap();
  return true;
}

bool panel_buffers_begin(void) {
  const size_t bytes = (size_t)LCD_WIDTH * (size_t)LCD_HEIGHT * sizeof(uint16_t);
  gFront = static_cast<uint16_t *>(
      heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  gBack = static_cast<uint16_t *>(
      heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (gFront == nullptr || gBack == nullptr) {
    heap_caps_free(gFront);
    heap_caps_free(gBack);
    gFront = nullptr;
    gBack = nullptr;
    ESP_LOGE(kTag, "framebuffer alloc failed");
    return false;
  }
  memset(gFront, 0, bytes);
  memset(gBack, 0, bytes);
  gGlassSynced = false;
  ESP_LOGI(kTag, "double buffer %u bytes x2", (unsigned)bytes);
  return true;
}

static void buf_fill_rect(int x, int y, int w, int h, uint16_t color565) {
  for (int row = 0; row < h; ++row) {
    uint16_t *dst = gBack + (size_t)(y + row) * LCD_WIDTH + x;
    for (int col = 0; col < w; ++col) {
      dst[col] = color565;
    }
  }
}

static uint16_t blend255(uint16_t dst, uint16_t src, int alpha) {
  if (alpha <= 0) {
    return dst;
  }
  if (alpha >= 255) {
    return src;
  }
  const int inv = 255 - alpha;
  const int dr = (dst >> 11) & 31;
  const int dg = (dst >> 5) & 63;
  const int db = dst & 31;
  const int sr = (src >> 11) & 31;
  const int sg = (src >> 5) & 63;
  const int sb = src & 31;
  const int r = (sr * alpha + dr * inv) / 255;
  const int g = (sg * alpha + dg * inv) / 255;
  const int b = (sb * alpha + db * inv) / 255;
  return static_cast<uint16_t>((r << 11) | (g << 5) | b);
}

int panel_text_width(const char *s) {
  int width = 0;
  int height = 0;
  glyph_line_size(s, &width, &height);
  return width;
}

static const int kTextCap = 96;

/* Alpha from the mapped glyph. RGB in the file is white; the caller tints. */
static void paint_rgba(uint16_t *base, int stride, int origin_x, int origin_y,
                       int glyph_w, int glyph_h, const uint8_t *rgba,
                       int clip_x, int clip_y, int clip_w, int clip_h,
                       uint16_t ink565) {
  const int clip_r = clip_x + clip_w;
  const int clip_b = clip_y + clip_h;
  for (int row = 0; row < glyph_h; ++row) {
    const int py = origin_y + row;
    for (int col = 0; col < glyph_w; ++col) {
      const int px = origin_x + col;
      const uint8_t alpha = rgba[(size_t)(row * glyph_w + col) * 4 + 3];
      if (alpha == 0 || px < clip_x || px >= clip_r || py < clip_y ||
          py >= clip_b) {
        continue;
      }
      uint16_t *dst = base + static_cast<size_t>(py) * stride + px;
      *dst = blend255(*dst, ink565, alpha);
    }
  }
}

static int layout_text(const char *s, LayBox *boxes, const uint8_t **rgba,
                       LayAt *placed, LayUnion *line) {
  const int n = glyph_line_items(s, boxes, rgba, kTextCap);
  if (n <= 0) {
    return 0;
  }
  lay_l2r(boxes, n, VAlign_bot, placed, line);
  return n;
}

static void push_rect(int x, int y, int w, int h) {
  int row = 0;
  while (row < h) {
    int rows = h - row;
    int max_rows = (LCD_WIDTH * kBandRows) / w;
    if (max_rows < 1) {
      max_rows = 1;
    }
    if (rows > max_rows) {
      rows = max_rows;
    }
    int n = 0;
    for (int r = 0; r < rows; ++r) {
      const uint16_t *src =
          gBack + (size_t)(y + row + r) * LCD_WIDTH + x;
      for (int c = 0; c < w; ++c) {
        gBand[n++] = swap16(src[c]);
      }
    }
    set_window(x, y + row, w, rows);
    write_pixels(gBand, (size_t)n);
    row += rows;
  }
}

static bool row_dirty_span(int y, int *x0, int *x1) {
  const uint16_t *back = gBack + (size_t)y * LCD_WIDTH;
  const uint16_t *front = gFront + (size_t)y * LCD_WIDTH;
  int left = -1;
  int right = -1;
  for (int x = 0; x < LCD_WIDTH; ++x) {
    if (back[x] != front[x]) {
      if (left < 0) {
        left = x;
      }
      right = x;
    }
  }
  if (left < 0) {
    return false;
  }
  *x0 = left;
  *x1 = right;
  return true;
}

/* Draw has already filled gBack. Push spans that differ, then make that
 * frame the one we compare against next time. */
void panel_present(void) {
  if (gFront == nullptr || gBack == nullptr) {
    return;
  }
  if (!gGlassSynced) {
    push_rect(0, 0, LCD_WIDTH, LCD_HEIGHT);
    gGlassSynced = true;
  } else {
    int y = 0;
    while (y < LCD_HEIGHT) {
      int x0 = 0;
      int x1 = 0;
      if (!row_dirty_span(y, &x0, &x1)) {
        y++;
        continue;
      }
      const int y0 = y;
      int ux0 = x0;
      int ux1 = x1;
      y++;
      while (y < LCD_HEIGHT && (y - y0) < kBandRows) {
        int nx0 = 0;
        int nx1 = 0;
        if (!row_dirty_span(y, &nx0, &nx1)) {
          break;
        }
        if (nx0 < ux0) {
          ux0 = nx0;
        }
        if (nx1 > ux1) {
          ux1 = nx1;
        }
        y++;
      }
      push_rect(ux0, y0, ux1 - ux0 + 1, y - y0);
    }
  }
  uint16_t *held = gFront;
  gFront = gBack;
  gBack = held;
}

void panel_fill_screen(uint16_t color565) {
  if (gBack != nullptr) {
    buf_fill_rect(0, 0, LCD_WIDTH, LCD_HEIGHT, color565);
    return;
  }
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

void panel_fill_rect(int x, int y, int w, int h, uint16_t color565) {
  if (w <= 0 || h <= 0) {
    return;
  }
  if (x < 0) {
    w += x;
    x = 0;
  }
  if (y < 0) {
    h += y;
    y = 0;
  }
  if (x >= LCD_WIDTH || y >= LCD_HEIGHT || w <= 0 || h <= 0) {
    return;
  }
  if (x + w > LCD_WIDTH) {
    w = LCD_WIDTH - x;
  }
  if (y + h > LCD_HEIGHT) {
    h = LCD_HEIGHT - y;
  }
  if (gBack != nullptr) {
    buf_fill_rect(x, y, w, h, color565);
    return;
  }
  const uint16_t swapped = swap16(color565);
  int row = 0;
  while (row < h) {
    int rows = h - row;
    if (rows > kBandRows) {
      rows = kBandRows;
    }
    for (int i = 0; i < w * rows; ++i) {
      gBand[i] = swapped;
    }
    set_window(x, y + row, w, rows);
    write_pixels(gBand, (size_t)w * (size_t)rows);
    row += rows;
  }
}

static void paint_line(uint16_t *base, int stride, int origin_x, int origin_y,
                       int local_x, int local_y, const LayBox *boxes,
                       const uint8_t **rgba, const LayAt *placed, int n,
                       int clip_x, int clip_y, int clip_w, int clip_h,
                       uint16_t ink565) {
  for (int i = 0; i < n; ++i) {
    if (rgba[i] == nullptr) {
      continue;
    }
    paint_rgba(base, stride, origin_x + lay_left(&placed[i]) - local_x,
               origin_y + lay_top(&placed[i]) - local_y, boxes[i].w, boxes[i].h,
               rgba[i], clip_x, clip_y, clip_w, clip_h, ink565);
  }
}

void panel_text(int x, int y, const char *s, int scale, uint16_t color565) {
  (void)scale;
  if (s == nullptr || s[0] == '\0') {
    return;
  }
  LayBox boxes[kTextCap];
  const uint8_t *rgba[kTextCap];
  LayAt placed[kTextCap];
  LayUnion line;
  const int n = layout_text(s, boxes, rgba, placed, &line);
  const int row_h = line.h;
  if (n <= 0 || row_h <= 0 || y < 0 || y + row_h > LCD_HEIGHT) {
    return;
  }
  if (gBack != nullptr) {
    buf_fill_rect(0, y, LCD_WIDTH, row_h, 0x0000);
    paint_line(gBack, LCD_WIDTH, x, y, line.x, line.y, boxes, rgba, placed, n, 0,
               y, LCD_WIDTH, row_h, color565);
    return;
  }
  if (row_h > kBandRows) {
    return;
  }
  for (int i = 0; i < LCD_WIDTH * row_h; ++i) {
    gBand[i] = 0x0000;
  }
  paint_line(gBand, LCD_WIDTH, x, 0, line.x, line.y, boxes, rgba, placed, n, 0, 0,
             LCD_WIDTH, row_h, color565);
  for (int i = 0; i < LCD_WIDTH * row_h; ++i) {
    gBand[i] = swap16(gBand[i]);
  }
  set_window(0, y, LCD_WIDTH, row_h);
  write_pixels(gBand, (size_t)LCD_WIDTH * row_h);
}

void panel_text_on(int x, int y, const char *s, int scale, uint16_t ink565,
                   uint16_t paper565) {
  (void)scale;
  if (s == nullptr || s[0] == '\0') {
    return;
  }
  LayBox boxes[kTextCap];
  const uint8_t *rgba[kTextCap];
  LayAt placed[kTextCap];
  LayUnion line;
  const int n = layout_text(s, boxes, rgba, placed, &line);
  const int row_w = line.w;
  const int row_h = line.h;
  if (n <= 0 || row_w <= 0 || row_h <= 0 || row_h > LCD_HEIGHT) {
    return;
  }
  if (x < 0 || y < 0 || x + row_w > LCD_WIDTH || y + row_h > LCD_HEIGHT) {
    return;
  }
  if (gBack != nullptr) {
    buf_fill_rect(x, y, row_w, row_h, paper565);
    paint_line(gBack, LCD_WIDTH, x, y, line.x, line.y, boxes, rgba, placed, n, x, y,
               row_w, row_h, ink565);
    return;
  }
  if (row_h > kBandRows) {
    return;
  }
  for (int i = 0; i < row_w * row_h; ++i) {
    gBand[i] = paper565;
  }
  paint_line(gBand, row_w, 0, 0, line.x, line.y, boxes, rgba, placed, n, 0, 0,
             row_w, row_h, ink565);
  for (int i = 0; i < row_w * row_h; ++i) {
    gBand[i] = swap16(gBand[i]);
  }
  set_window(x, y, row_w, row_h);
  write_pixels(gBand, (size_t)row_w * row_h);
}
