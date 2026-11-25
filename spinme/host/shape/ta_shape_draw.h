/* Tagged-union shape table + XY RLC glass path (todo:6bc4b036 Draw reshape). */
#ifndef SPINME_TA_SHAPE_DRAW_H
#define SPINME_TA_SHAPE_DRAW_H

#include "ta_uilayout.h"

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TA_SD_SLOTS 1024
#define TA_SD_NONE 0u
#define TA_SD_LOCKED_MAX 127u /* indices 1..127 locked assets; never GC into */
#define TA_SD_RLC_N 2         /* default RLC words/row when nibble unset */
#define TA_SD_RLC_N_MAX 15    /* nibble max (4 bits); 15 words => 30 ranges */
#define TA_SD_RLC_RANGES_PER_WORD 2u
#define TA_SD_BADNESS_WINDOW 100u /* paints before rolling avg snapshot */
/*
 * Auto-tune conversion: 1 unused RLC range slot <-> this many overflow px.
 * Indifference: one greedy merge of a modest inter-ink gap (~4 /2-units = 8 px)
 * equals one idle slot. combined = ov + lambda * sl (px-equivalent / line).
 * Raise lambda to prefer fewer words (tolerate more over); lower to buy slots.
 */
#define TA_SD_BADNESS_PX_PER_SLACK_SLOT 8.f
#define TA_SD_REF_BITS 10
#define TA_SD_REF_MASK ((1u << TA_SD_REF_BITS) - 1u)

enum {
    TA_SD_TAG_NONE = 0,
    TA_SD_TAG_BITMAP = 1,
    TA_SD_TAG_COMPOSITE = 2, /* up to 3 child refs via 3x10 pack */
    TA_SD_TAG_XY = 3         /* absolute place; only tag that reaches glass */
};

/* One RLC word: four bytes off1,len1,off2,len2 in /2 units (0 len = null). */
typedef uint32_t ta_sd_rlc_word_t;

typedef struct ta_sd_shape {
    uint8_t tag;
    /* bit0 dirty; bits4..7 rlc_n words/row (0 => TA_SD_RLC_N). */
    uint8_t flags;
    uint16_t w;
    uint16_t h;
    ta_pack66_t *pixels; /* owned; NULL if none. XY: w*h words then rlc. */
    /*
     * TeX-style badness (XY): mean per raster line (float).
     * 47 transparent px on one line is bad; 47 across 512 lines is ~0.09/line.
     */
    float badness_overflow_avg;
    float badness_slack_avg;
    uint32_t badness_paints;
    union {
        struct {
            uint32_t refs; /* 2 tag bits + 3x10 child idxs (tag=3 => 3x10) */
        } composite;
        struct {
            uint16_t child;
            int16_t x;
            int16_t y;
        } xy;
    } u;
} ta_sd_shape_t;

void ta_sd_reset(void);
ta_sd_shape_t *ta_sd_get(unsigned idx);

/* Pack/unpack exactly 3x10-bit refs in low 30 bits (top 2 = 11b tag). */
uint32_t ta_sd_pack3(unsigned a, unsigned b, unsigned c);
void ta_sd_unpack3(uint32_t word, unsigned *a, unsigned *b, unsigned *c);

/*
 * Alloc bitmap pixels (and XY RLC trailer). Frees prior. Returns 0 ok.
 * For XY, pixels layout = w*h pack66 + h*rlc_n rlc words (default rlc_n).
 */
int ta_sd_alloc_bitmap(unsigned idx, uint8_t tag, uint16_t w, uint16_t h);
/* Like alloc_bitmap; for XY, rlc_n_words 0 => TA_SD_RLC_N. */
int ta_sd_alloc_bitmap_rlc(unsigned idx, uint8_t tag, uint16_t w, uint16_t h,
                           uint8_t rlc_n_words);
void ta_sd_free(unsigned idx);

unsigned ta_sd_rlc_n(const ta_sd_shape_t *s);
unsigned ta_sd_rlc_max_ranges(const ta_sd_shape_t *s);

/* RLC helpers: units are /2 (pixel_off = unit*2). */
void ta_sd_rlc_clear_row(ta_sd_rlc_word_t *row_words, unsigned n_words);
int ta_sd_rlc_set_ranges(ta_sd_rlc_word_t *row_words, unsigned n_words,
                         const uint8_t *off_u, const uint8_t *len_u, int n_in);
/* Merge ranges until <= max_out; sorted non-overlapping. */
int ta_sd_rlc_merge_to_n(uint8_t *off_u, uint8_t *len_u, int n_in, int max_out);
/* Opaque (non-clear) runs on one row -> /2 off/len; returns run count. */
int ta_sd_collect_opaque_runs(const ta_pack66_t *row, uint16_t w, uint8_t *off,
                              uint8_t *len, int max_n);

ta_sd_rlc_word_t *ta_sd_xy_rlc(ta_sd_shape_t *xy);

/*
 * Sample current RLC vs pixmap into shape badness (mean per line):
 * - overflow: fully transparent pixels inside combined RLC / h
 * - slack: unused range slots / h
 * Running mean across paints (float).
 */
void ta_sd_xy_sample_badness(ta_sd_shape_t *xy);

/* Mean-per-line averages (0 if no samples yet). */
float ta_sd_badness_overflow(const ta_sd_shape_t *s);
float ta_sd_badness_slack(const ta_sd_shape_t *s);
/* ov + TA_SD_BADNESS_PX_PER_SLACK_SLOT * sl (px-equivalent / line). */
float ta_sd_badness_combined(const ta_sd_shape_t *s);

/*
 * Pick rlc_n in [n_lo,n_hi] minimizing mean-line (ov + lambda*sl) for a
 * pack66 pixmap (opaque vs clear silhouette + greedy merge). Returns best N
 * (at least 1). Used by L2R / viewport after bake.
 */
unsigned ta_sd_optimize_rlc_n(const ta_pack66_t *px, uint16_t w, uint16_t h,
                              unsigned n_lo, unsigned n_hi);

/* One line per XY: "idx ov=.. sl=.. bad=.. paints=.. rlc_n=.." */
size_t ta_sd_format_badness_report(char *dst, size_t cap);

/*
 * pack66 blend for glass write:
 * - TA_PACK66_TRANSPARENT => skip (transparent hole)
 * - a2==0 and word!=0 => clamped additive per channel (no shift)
 * - a2 1..2 => src-over; a2==3 => copy
 */
/* Raw pack66 word (allows a2==0 nonzero RGB for additive). */
ta_pack66_t ta_sd_word(uint8_t r6, uint8_t g6, uint8_t b6, uint8_t a2);

ta_pack66_t ta_sd_blend(ta_pack66_t dst, ta_pack66_t src);

void ta_sd_blit(ta_pack66_t *dst, uint16_t dw, uint16_t dh, int ox, int oy,
                const ta_pack66_t *src, uint16_t sw, uint16_t sh);

/*
 * Build XY RLC from changed runs (old vs new), then greedy-merge smallest
 * gaps until <= 2*rlc_n ranges. old_px NULL => all transparent (content
 * silhouette vs clear).
 */
void ta_sd_xy_derive_rlc(ta_sd_shape_t *xy, const ta_pack66_t *old_px,
                         const ta_pack66_t *new_px);

/* Alias: content-derived RLC vs clear (same as derive_rlc(xy, NULL, px)). */
void ta_sd_xy_mark_full_dirty(ta_sd_shape_t *xy);

/* Clear XY pixmap and blit child BITMAP into it (0,0). 0 ok. */
int ta_sd_xy_rebuild_from_child(unsigned xy_idx);

/*
 * Glass write: only XYShape reaches the glass. Blend RLC dirty spans of xy
 * onto glass at (xy.x, xy.y). Empty RLC => no-op.
 */
void ta_sd_xy_blit_glass(ta_pack66_t *glass, uint16_t gw, uint16_t gh,
                         unsigned xy_idx);

/* Farthest -> nearest: blit each XY's dirty spans. */
void ta_sd_glass_paint_xys(ta_pack66_t *glass, uint16_t gw, uint16_t gh,
                           const unsigned *xy_idxs, size_t n);

/*
 * Device/host push seam: for each dirty RLC span call push(x,y,w,h,px,stride).
 * Pixels are the XY bitmap (precomposed); no further blend.
 */
typedef void (*ta_sd_push_rect_fn)(int x, int y, int w, int h,
                                   const ta_pack66_t *px, int stride_px,
                                   void *ctx);
int ta_sd_xy_push_dirty(unsigned xy_idx, ta_sd_push_rect_fn push, void *ctx);

/* Stop-the-world tracing compacting GC. root kept; never into 1..LOCKED_MAX. */
int ta_sd_gc(unsigned root);

#ifdef __cplusplus
}
#endif
#endif
