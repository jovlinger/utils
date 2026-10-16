#include "glyph_file.h"

#include <esp_log.h>

static const char *kTag = "glyphs";
static const uint32_t kMagic = 0x31594C47u;
static const int kItemCap = 96;

extern const uint8_t glyphs_bin_start[] asm("glyphs_bin_start");
extern const uint8_t glyphs_bin_end[] asm("glyphs_bin_end");

/* The app image is already mapped through the flash cache. glyphs.bin is
 * linked into .rodata, so this pointer is that mapping. */
static const uint8_t *gMap = nullptr;
static size_t gMapLen = 0;

static uint32_t rd32(const uint8_t *p) {
  return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
         ((uint32_t)p[3] << 24);
}

static int rd_i16(const uint8_t *p) {
  int v = (int)p[0] | ((int)p[1] << 8);
  if (v & 0x8000) {
    v -= 0x10000;
  }
  return v;
}

static int rd_u16(const uint8_t *p) {
  return (int)p[0] | ((int)p[1] << 8);
}

bool glyph_file_mmap(void) {
  if (gMap != nullptr) {
    return true;
  }
  const uintptr_t start = reinterpret_cast<uintptr_t>(glyphs_bin_start);
  const uintptr_t end = reinterpret_cast<uintptr_t>(glyphs_bin_end);
  if (end < start + 40) {
    ESP_LOGE(kTag, "glyph file is too small");
    return false;
  }
  if (rd32(glyphs_bin_start) != kMagic) {
    ESP_LOGE(kTag, "glyph file magic mismatch");
    return false;
  }
  gMap = glyphs_bin_start;
  gMapLen = (size_t)(end - start);
  ESP_LOGI(kTag, "mapped %u bytes", (unsigned)gMapLen);
  return true;
}

static bool ready(void) {
  if (gMap != nullptr) {
    return true;
  }
  return glyph_file_mmap();
}

static uint32_t field(int index) {
  if (!ready()) {
    return 0;
  }
  return rd32(gMap + (size_t)index * 4);
}

int glyph_body_h(void) { return (int)field(3); }

LayBox glyph_letter_hshim(void) { return lay_hshim((int)field(4)); }

LayBox glyph_word_hshim(void) { return lay_hshim((int)field(5)); }

LayBox glyph_line_vshim(void) { return lay_vshim((int)field(6)); }

LayBox glyph_section_vshim(void) { return lay_vshim((int)field(7)); }

static const uint8_t *find_rec(uint32_t key) {
  if (!ready()) {
    return nullptr;
  }
  const uint32_t count = field(2);
  const uint32_t index_off = field(8);
  for (uint32_t i = 0; i < count; ++i) {
    const uint8_t *ent = gMap + index_off + (size_t)i * 8;
    if (ent + 8 > gMap + gMapLen) {
      return nullptr;
    }
    if (rd32(ent) == key) {
      const uint32_t off = rd32(ent + 4);
      if (off + 12 > gMapLen) {
        return nullptr;
      }
      return gMap + off;
    }
  }
  return nullptr;
}

static const uint8_t *find_glyph(unsigned char code, int *w, int *h,
                                 const uint8_t **rgba) {
  const uint8_t *rec = find_rec(code);
  if (rec == nullptr && code != '?') {
    rec = find_rec('?');
  }
  if (rec == nullptr) {
    return nullptr;
  }
  *w = rd_u16(rec + 8);
  *h = rd_u16(rec + 10);
  *rgba = rec + 12;
  return rec;
}

int glyph_line_items(const char *s, LayBox *boxes, const uint8_t **rgba, int cap) {
  if (s == nullptr || boxes == nullptr || rgba == nullptr || cap <= 0) {
    return 0;
  }
  int n = 0;
  bool prev = false;
  for (const char *p = s; *p != '\0' && n < cap; ++p) {
    if (*p == ' ') {
      boxes[n] = glyph_word_hshim();
      rgba[n] = nullptr;
      n++;
      prev = false;
      continue;
    }
    if (prev && n < cap) {
      boxes[n] = glyph_letter_hshim();
      rgba[n] = nullptr;
      n++;
    }
    if (n >= cap) {
      break;
    }
    int w = 0;
    int h = 0;
    const uint8_t *pixels = nullptr;
    if (find_glyph(static_cast<unsigned char>(*p), &w, &h, &pixels) == nullptr) {
      prev = false;
      continue;
    }
    boxes[n].w = w;
    boxes[n].h = h;
    rgba[n] = pixels;
    n++;
    prev = true;
  }
  return n;
}

int glyph_line_size(const char *s, int *w, int *h) {
  LayBox boxes[kItemCap];
  const uint8_t *rgba[kItemCap];
  const int n = glyph_line_items(s, boxes, rgba, kItemCap);
  bool any = false;
  for (int i = 0; i < n; ++i) {
    if (rgba[i] != nullptr) {
      any = true;
      break;
    }
  }
  if (!any) {
    if (w != nullptr) {
      *w = 0;
    }
    if (h != nullptr) {
      *h = 0;
    }
    return 0;
  }
  LayAt placed[kItemCap];
  LayUnion line;
  lay_l2r(boxes, n, VAlign_bot, placed, &line);
  if (w != nullptr) {
    *w = line.w;
  }
  if (h != nullptr) {
    *h = line.h;
  }
  return 1;
}
