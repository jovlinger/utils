/* UILayout display-list word + ShapeBitMap exemplar (pack66 pixels). */
#ifndef SPINME_TA_UILAYOUT_H
#define SPINME_TA_UILAYOUT_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif
/*
 * accept_hit packing CHOICE (WorkItem 0006): parallel flags array.
 * UILayout stays a tight 32-bit word (dirty/x/y/shape). Hit eligibility
 * lives in a sibling uint8_t accept_hit[i] of the same length as uilo[].
 * Do not steal the 1-bit _pad for accept_hit -- keep pad for alignment
 * experiments; opacity sampling stays optional later inside hit walk.
 */

#define TA_SHAPE_MAX 1024
#define TA_UILAYOUT_MAX 64

/* pack66 word (match uimk2_blit): R6 | G6<<8 | B6<<16 | A2<<24. */
typedef uint32_t ta_pack66_t;

#define TA_PACK66_A2_SHIFT 24
/* Exact skip / hole. Nonzero RGB with a2==0 is clamped-additive, not this. */
#define TA_PACK66_TRANSPARENT ((ta_pack66_t)0u)

ta_pack66_t ta_pack66_rgba(uint8_t r6, uint8_t g6, uint8_t b6, uint8_t a2);
void ta_unpack66(ta_pack66_t px, uint8_t *r6, uint8_t *g6, uint8_t *b6,
                 uint8_t *a2);

/*
 * UILayout: one 32-bit word.
 *  bit0     dirty
 *  bit1     pad
 *  bit2-11  x (int10, 0..1023)
 *  bit12-21 y (int10)
 *  bit22-31 shape idx (idx10)
 */
typedef uint32_t ta_uilayout_t;

#define TA_UILO_DIRTY_SHIFT 0
#define TA_UILO_X_SHIFT 2
#define TA_UILO_Y_SHIFT 12
#define TA_UILO_SHAPE_SHIFT 22
#define TA_UILO_FIELD_MASK 0x3ffu

ta_uilayout_t ta_uilo_make(int dirty, int x, int y, unsigned shape);
int ta_uilo_dirty(ta_uilayout_t w);
int ta_uilo_x(ta_uilayout_t w);
int ta_uilo_y(ta_uilayout_t w);
unsigned ta_uilo_shape(ta_uilayout_t w);
ta_uilayout_t ta_uilo_set_dirty(ta_uilayout_t w, int dirty);

enum {
    TA_SHAPE_TAG_BITMAP = 1
};

typedef struct ta_shape_bitmap {
    uint8_t tag; /* TA_SHAPE_TAG_BITMAP */
    uint8_t dirty;
    uint16_t w;
    uint16_t h;
    ta_pack66_t *pixels; /* w*h pack66; owned by caller/table */
} ta_shape_bitmap_t;

void ta_shape_table_reset(void);
int ta_shape_table_set(unsigned idx, ta_shape_bitmap_t *shape);
ta_shape_bitmap_t *ta_shape_table_get(unsigned idx);

#ifdef __cplusplus
}
#endif
#endif
