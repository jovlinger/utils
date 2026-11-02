/* Draw.update: defs + dirty only (no pixmap mutation). */
#ifndef SPINME_TA_DRAW_UPDATE_H
#define SPINME_TA_DRAW_UPDATE_H

#include "ta_shape_l2r.h"
#include "ta_uilayout.h"

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif
enum {
    TA_UPD_NOOP = 0,
    TA_UPD_REPRESENT_TIME = 1
};

typedef struct ta_draw_node {
    unsigned shape_idx;
    uint8_t update_enum;
    /* Static shadow: idxs of higher shapes dirtied when this is dirty. */
    const unsigned *shadow_higher;
    size_t shadow_n;
} ta_draw_node_t;

typedef struct ta_draw_scene {
    ta_uilayout_t *uilo;
    uint8_t *accept_hit; /* unused here; parallel array */
    size_t n_uilo;
    ta_draw_node_t *nodes;
    size_t n_nodes;
    /* Clock digits glyph idxs '0'..'9' for represent-time (10 entries). */
    unsigned digit_glyph[10];
    unsigned colon_glyph; /* ':' glyph idx; 0 falls back to digit_glyph[0] */
    char clock_hhmmss[9]; /* "HH:MM:SS" + NUL; input to represent-time */
} ta_draw_scene_t;

/* Walk nodes; may set Shape.dirty + UILayout.dirty; never touches *pixels. */
int ta_draw_update(ta_draw_scene_t *scene);

#ifdef __cplusplus
}
#endif
#endif
