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

enum {
    TA_KV_EDITOR_FIELD_KEY = 0,
    TA_KV_EDITOR_FIELD_VAL = 1
};

typedef struct ta_kv_editor {
    ta_shape_bitmap_t panel;
    ta_pack66_t *pixels; /* panel_w * panel_h; glue-owned or alloc */
    uint16_t panel_w;
    uint16_t panel_h;
    unsigned cursor; /* index into ta_kv_count() */
    char key[TA_KV_EDITOR_LINE];
    char val[TA_KV_EDITOR_LINE];
    int ready;
    int editing;           /* 1 after enter; 0 = view/navigate records */
    unsigned field;        /* KEY or VAL while editing */
    unsigned char_pos;     /* caret inside the active field */
    char charset[96];      /* printable rotary alphabet */
    size_t charset_n;
    unsigned char_sel;     /* index into charset for the caret cell */
} ta_kv_editor_t;

void ta_kv_editor_reset(ta_kv_editor_t *ed);
/* Bind a panel buffer; does not own pixels. -1 on bad args. */
int ta_kv_editor_bind(ta_kv_editor_t *ed, ta_pack66_t *pixels, uint16_t w,
                      uint16_t h);
/* Reload key/val from KV at cursor; fill panel with a simple view pattern. */
int ta_kv_editor_refresh(ta_kv_editor_t *ed);
/* Navigate records when not editing; move caret when editing. */
unsigned ta_kv_editor_fwd(ta_kv_editor_t *ed);
unsigned ta_kv_editor_back(ta_kv_editor_t *ed);
/* Enter: start edit on VAL (or toggle field). Commit + exit when already
 * editing the same field twice in a row is via ta_kv_editor_commit. */
int ta_kv_editor_enter(ta_kv_editor_t *ed);
/* Rotary steps change the character under the caret while editing. */
int ta_kv_editor_rotate(ta_kv_editor_t *ed, int8_t steps);
/* Write the current key/val back through ta_kv_put; leave edit mode. */
int ta_kv_editor_commit(ta_kv_editor_t *ed);
int ta_kv_editor_editing(const ta_kv_editor_t *ed);
unsigned ta_kv_editor_field(const ta_kv_editor_t *ed);
unsigned ta_kv_editor_char_pos(const ta_kv_editor_t *ed);
unsigned ta_kv_editor_cursor(const ta_kv_editor_t *ed);
const char *ta_kv_editor_key(const ta_kv_editor_t *ed);
const char *ta_kv_editor_val(const ta_kv_editor_t *ed);
/* Install panel into the shape table at TA_KV_EDITOR_IDX. */
int ta_kv_editor_install_shape(ta_kv_editor_t *ed);

#ifdef __cplusplus
}
#endif

#endif
