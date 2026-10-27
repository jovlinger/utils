#include "rom_jpeg.h"

#include <stdlib.h>
#include <string.h>

#include <Arduino.h>
#include <esp_heap_caps.h>

extern "C" {
#include "rom/tjpgd.h"
}

static const size_t kWorkBytes = 3100u;

struct RomJpegCtx {
  const uint8_t *data;
  size_t len;
  size_t off;
  uint8_t *dst;
  uint16_t dst_w;
  uint16_t dst_h;
  uint16_t out_w;
  uint16_t out_h;
};

static UINT rom_jpeg_in(JDEC *jd, BYTE *buf, UINT nbyte) {
  RomJpegCtx *ctx = static_cast<RomJpegCtx *>(jd->device);
  size_t left;
  size_t n;
  if (ctx == nullptr) {
    return 0;
  }
  left = (ctx->off < ctx->len) ? (ctx->len - ctx->off) : 0u;
  n = nbyte;
  if (n > left) {
    n = left;
  }
  if (buf != nullptr && n > 0u) {
    memcpy(buf, ctx->data + ctx->off, n);
  }
  ctx->off += n;
  return (UINT)n;
}

/* Coarsest scale with out >= dst on both axes; else 0 (1/1). */
static uint8_t pick_scale_nn(UINT src_w, UINT src_h, uint16_t dst_w,
                             uint16_t dst_h) {
  uint8_t best = 0;
  uint8_t s;
  for (s = 0; s <= 3; s++) {
    UINT div = 1u << s;
    UINT ow = src_w / div;
    UINT oh = src_h / div;
    if (ow == 0u) {
      ow = 1u;
    }
    if (oh == 0u) {
      oh = 1u;
    }
    if (ow >= dst_w && oh >= dst_h) {
      best = s;
    }
  }
  return best;
}

/* Dest dx with floor(dx * out / dst) in [sx0, sx1], inclusive. */
static void nn_dest_span(UINT sx0, UINT sx1, UINT out, UINT dst, UINT *d0,
                         UINT *d1) {
  /* ceil(sx0 * dst / out) .. first dx with sx > sx1. */
  UINT a;
  UINT b;
  if (out == 0u || dst == 0u) {
    *d0 = 0;
    *d1 = 0;
    return;
  }
  a = (UINT)(((uint32_t)sx0 * dst + (out - 1u)) / out);
  b = (UINT)(((uint32_t)(sx1 + 1u) * dst + (out - 1u)) / out);
  if (a > dst) {
    a = dst;
  }
  if (b > dst) {
    b = dst;
  }
  if (b < a) {
    b = a;
  }
  *d0 = a;
  *d1 = b;
}

static UINT rom_jpeg_out_nn(JDEC *jd, void *bitmap, JRECT *rect) {
  RomJpegCtx *ctx = static_cast<RomJpegCtx *>(jd->device);
  const uint8_t *rgb;
  UINT left;
  UINT right;
  UINT top;
  UINT bottom;
  UINT bw;
  UINT dleft;
  UINT dright;
  UINT dtop;
  UINT dbottom;
  UINT dx;
  UINT dy;
  if (ctx == nullptr || bitmap == nullptr || rect == nullptr) {
    return 0;
  }
  if (ctx->dst == nullptr || ctx->out_w == 0u || ctx->out_h == 0u ||
      ctx->dst_w == 0u || ctx->dst_h == 0u) {
    return 0;
  }
  rgb = static_cast<const uint8_t *>(bitmap);
  left = rect->left;
  right = rect->right;
  top = rect->top;
  bottom = rect->bottom;
  bw = right - left + 1u;
  /* Own every dest pixel whose NN source falls in this MCU -- no gaps
   * between adjacent MCU dest ranges (unlike expanding the MCU rect). */
  nn_dest_span(left, right, ctx->out_w, ctx->dst_w, &dleft, &dright);
  nn_dest_span(top, bottom, ctx->out_h, ctx->dst_h, &dtop, &dbottom);
  for (dy = dtop; dy < dbottom; dy++) {
    UINT sy = (UINT)((uint32_t)dy * ctx->out_h / ctx->dst_h);
    if (sy < top || sy > bottom) {
      continue;
    }
    for (dx = dleft; dx < dright; dx++) {
      UINT sx = (UINT)((uint32_t)dx * ctx->out_w / ctx->dst_w);
      const uint8_t *p;
      uint8_t *d;
      if (sx < left || sx > right) {
        continue;
      }
      p = rgb + ((size_t)(sy - top) * (size_t)bw + (size_t)(sx - left)) * 3u;
      d = ctx->dst + ((size_t)dy * (size_t)ctx->dst_w + (size_t)dx) * 4u;
      d[0] = p[0];
      d[1] = p[1];
      d[2] = p[2];
      d[3] = 255;
    }
  }
  return 1;
}

bool rom_jpeg_decode_nn_rgba(const uint8_t *jpeg, size_t len, uint8_t *dst,
                             uint16_t dst_w, uint16_t dst_h, RomJpegInfo *info) {
  JDEC jdec;
  JRESULT res;
  void *work;
  RomJpegCtx ctx;
  uint32_t t0;
  uint8_t scale;
  size_t i;
  size_t npix;
  if (info != nullptr) {
    memset(info, 0, sizeof *info);
  }
  if (jpeg == nullptr || len < 4u || dst == nullptr || dst_w == 0u ||
      dst_h == 0u) {
    return false;
  }
  npix = (size_t)dst_w * (size_t)dst_h;
  for (i = 0; i < npix; i++) {
    dst[i * 4u + 0u] = 0;
    dst[i * 4u + 1u] = 0;
    dst[i * 4u + 2u] = 0;
    dst[i * 4u + 3u] = 255;
  }
  work = heap_caps_malloc(kWorkBytes, MALLOC_CAP_DEFAULT);
  if (work == nullptr) {
    work = malloc(kWorkBytes);
  }
  if (work == nullptr) {
    return false;
  }
  ctx.data = jpeg;
  ctx.len = len;
  ctx.off = 0;
  ctx.dst = dst;
  ctx.dst_w = dst_w;
  ctx.dst_h = dst_h;
  ctx.out_w = 0;
  ctx.out_h = 0;
  t0 = millis();
  res = jd_prepare(&jdec, rom_jpeg_in, work, (UINT)kWorkBytes, &ctx);
  if (info != nullptr) {
    info->jd_prepare = (int)res;
    info->dst_w = dst_w;
    info->dst_h = dst_h;
  }
  if (res != JDR_OK) {
    free(work);
    if (info != nullptr) {
      info->decode_ms = millis() - t0;
    }
    return false;
  }
  scale = pick_scale_nn(jdec.width, jdec.height, dst_w, dst_h);
  ctx.out_w = (uint16_t)(jdec.width / (1u << scale));
  ctx.out_h = (uint16_t)(jdec.height / (1u << scale));
  if (ctx.out_w == 0) {
    ctx.out_w = 1;
  }
  if (ctx.out_h == 0) {
    ctx.out_h = 1;
  }
  if (info != nullptr) {
    info->src_w = (uint16_t)jdec.width;
    info->src_h = (uint16_t)jdec.height;
    info->out_w = ctx.out_w;
    info->out_h = ctx.out_h;
    info->scale = scale;
  }
  res = jd_decomp(&jdec, rom_jpeg_out_nn, scale);
  if (info != nullptr) {
    info->jd_decomp = (int)res;
    info->decode_ms = millis() - t0;
  }
  free(work);
  return res == JDR_OK;
}
