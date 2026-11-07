/* KV config editor: view-first page for SwapShape (fwd/back navigate). */
#ifndef SPINME_TA_KV_EDITOR_H
#define SPINME_TA_KV_EDITOR_H

#include "ta_uilayout.h"

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TA_KV_EDITOR_LINE 96
#define TA_KV_EDITOR_IDX 921 /* shape table slot for the panel bitmap */

typedef struct ta_kv_editor {
    ta_shape_bitmap_t panel;
    ta_pack66_t *pixels; /* panel_w * panel_h; glue-owned or alloc */
    uint16_t panel_w;
    uint16_t panel_h;
    unsigned cursor; /* index into ta_kv_count() */
    char key[TA_KV_EDITOR_LINE];
    char val[TA_KV_EDITOR_LINE];
    int ready;
} ta_kv_editor_t;

void ta_kv_editor_reset(ta_kv_editor_t *ed);
/* Bind a panel buffer; does not own pixels. -1 on bad args. */
int ta_kv_editor_bind(ta_kv_editor_t *ed, ta_pack66_t *pixels, uint16_t w,
                      uint16_t h);
/* Reload key/val from KV at cursor; fill panel with a simple view pattern. */
int ta_kv_editor_refresh(ta_kv_editor_t *ed);
/* Navigate; wraps. Returns new cursor. */
unsigned ta_kv_editor_fwd(ta_kv_editor_t *ed);
unsigned ta_kv_editor_back(ta_kv_editor_t *ed);
unsigned ta_kv_editor_cursor(const ta_kv_editor_t *ed);
const char *ta_kv_editor_key(const ta_kv_editor_t *ed);
const char *ta_kv_editor_val(const ta_kv_editor_t *ed);
/* Install panel into the shape table at TA_KV_EDITOR_IDX. */
int ta_kv_editor_install_shape(ta_kv_editor_t *ed);

#ifdef __cplusplus
}
#endif

#endif
