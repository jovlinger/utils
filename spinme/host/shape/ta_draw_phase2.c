#include "ta_draw_phase2.h"

#include "ta_shape_draw.h"
#include "ta_shape_l2r.h"
#include "ta_viewport.h"

#include <string.h>

#define TA_P2_MAX_SHAPES 64
#define TA_P2_MAX_RANGES (TA_SD_RLC_N_MAX * TA_SD_RLC_RANGES_PER_WORD)

typedef struct ta_p2_cursor {
    unsigned shape_idx;
    int ox;
    int oy;
    uint16_t w;
    uint16_t h;
    const ta_pack66_t *px;
    unsigned max_r;
    uint16_t row;
    int ri;
    int nr;
    uint8_t off[TA_P2_MAX_RANGES];
    uint8_t len[TA_P2_MAX_RANGES];
    int alive;
    ta_rect_t exterior;
} ta_p2_cursor_t;

static int cursor_load_row(ta_p2_cursor_t *c) {
    while (c->row < c->h) {
        const ta_pack66_t *rowpx = c->px + (size_t)c->row * (size_t)c->w;
        int nr;

        nr = ta_sd_collect_opaque_runs(rowpx, c->w, c->off, c->len,
                                       (int)TA_P2_MAX_RANGES);
        nr = ta_sd_rlc_merge_to_n(c->off, c->len, nr, (int)c->max_r);
        if (nr < 0) {
            nr = 0;
        }
        c->nr = nr;
        c->ri = 0;
        if (c->nr > 0) {
            return 1;
        }
        c->row++;
    }
    c->alive = 0;
    return 0;
}

static int cursor_head_y(const ta_p2_cursor_t *c) {
    return c->oy + (int)c->row;
}

static int cursor_head_x(const ta_p2_cursor_t *c) {
    return c->ox + (int)c->off[c->ri] * 2;
}

/* True if a is strictly before b in merge order (y, then x, then shape_idx). */
static int cursor_before(const ta_p2_cursor_t *a, const ta_p2_cursor_t *b) {
    int ya = cursor_head_y(a);
    int yb = cursor_head_y(b);

    if (ya != yb) {
        return ya < yb;
    }
    {
        int xa = cursor_head_x(a);
        int xb = cursor_head_x(b);

        if (xa != xb) {
            return xa < xb;
        }
    }
    return a->shape_idx < b->shape_idx;
}

static int cursor_advance(ta_p2_cursor_t *c) {
    c->ri++;
    if (c->ri < c->nr) {
        return 1;
    }
    c->row++;
    return cursor_load_row(c);
}

static unsigned shape_max_r(const ta_shape_bitmap_t *hdr) {
    unsigned n = ta_shape_flags_rlc_n(hdr->flags);

    if (n == 0u) {
        n = 1u;
    }
    if (n > TA_SD_RLC_N_MAX) {
        n = TA_SD_RLC_N_MAX;
    }
    return n * TA_SD_RLC_RANGES_PER_WORD;
}

static int fill_ext(const ta_shape_bitmap_t *hdr, ta_uilayout_t w,
                    ta_rect_t *ext) {
    ext->x = ta_uilo_x(w);
    ext->y = ta_uilo_y(w);
    ext->w = (int)hdr->w;
    ext->h = (int)hdr->h;
    if (hdr->tag == TA_SHAPE_TAG_L2R) {
        const ta_shape_l2r_t *l2r = (const ta_shape_l2r_t *)(const void *)hdr;
        ext->w = (int)l2r->w;
        ext->h = (int)l2r->h;
    } else if (hdr->tag == TA_SHAPE_TAG_VIEWPORT) {
        const ta_shape_viewport_t *vp =
            (const ta_shape_viewport_t *)(const void *)hdr;
        ext->w = (int)vp->w;
        ext->h = (int)vp->h;
    }
    return ext->w > 0 && ext->h > 0 && hdr->pixels != NULL;
}

typedef struct {
    ta_phase2_frag_fn fn;
    void *ctx;
    ta_phase2_push_t *out;
    size_t out_cap;
    size_t npush;
    uint8_t seen[TA_P2_MAX_SHAPES];
    unsigned seen_idx[TA_P2_MAX_SHAPES];
    size_t nseen;
    int err;
} ta_p2_emit_t;

static void emit_frag(ta_p2_emit_t *e, const ta_p2_cursor_t *c) {
    ta_phase2_frag_t frag;
    size_t s;

    frag.x = cursor_head_x(c);
    frag.y = cursor_head_y(c);
    frag.w = (int)c->len[c->ri] * 2;
    if (frag.w <= 0) {
        frag.w = 1;
    }
    frag.shape_idx = c->shape_idx;
    if (e->fn != NULL) {
        e->fn(&frag, e->ctx);
    }
    if (e->out == NULL) {
        return;
    }
    for (s = 0; s < e->nseen; s++) {
        if (e->seen_idx[s] == c->shape_idx) {
            return;
        }
    }
    if (e->npush >= e->out_cap || e->nseen >= TA_P2_MAX_SHAPES) {
        e->err = 1;
        return;
    }
    e->seen_idx[e->nseen++] = c->shape_idx;
    e->out[e->npush].exterior = c->exterior;
    e->out[e->npush].shape_idx = c->shape_idx;
    e->npush++;
}

static int run_merge(ta_draw_scene_t *scene, ta_p2_emit_t *e) {
    ta_p2_cursor_t curs[TA_P2_MAX_SHAPES];
    size_t nc = 0;
    size_t i;

    if (scene == NULL) {
        return -1;
    }
    for (i = 0; i < scene->n_uilo; i++) {
        ta_uilayout_t w = scene->uilo[i];
        unsigned sidx;
        ta_shape_bitmap_t *hdr;
        ta_p2_cursor_t *c;

        if (!ta_uilo_dirty(w)) {
            continue;
        }
        sidx = ta_uilo_shape(w);
        hdr = ta_shape_table_get(sidx);
        if (hdr == NULL || !ta_shape_flags_dirty(hdr->flags)) {
            continue;
        }
        if (nc >= TA_P2_MAX_SHAPES) {
            return -1;
        }
        c = &curs[nc];
        memset(c, 0, sizeof(*c));
        c->shape_idx = sidx;
        if (!fill_ext(hdr, w, &c->exterior)) {
            hdr->flags = ta_shape_flags_set_dirty(hdr->flags, 0);
            scene->uilo[i] = ta_uilo_set_dirty(w, 0);
            continue;
        }
        c->ox = c->exterior.x;
        c->oy = c->exterior.y;
        c->w = (uint16_t)c->exterior.w;
        c->h = (uint16_t)c->exterior.h;
        c->px = hdr->pixels;
        c->max_r = shape_max_r(hdr);
        c->row = 0;
        c->alive = 1;
        if (!cursor_load_row(c)) {
            /* No opaque runs: still record exterior once for glass push. */
            if (e->out != NULL && e->npush < e->out_cap) {
                e->out[e->npush].exterior = c->exterior;
                e->out[e->npush].shape_idx = sidx;
                e->npush++;
            }
        } else {
            nc++;
        }
        hdr->flags = ta_shape_flags_set_dirty(hdr->flags, 0);
        scene->uilo[i] = ta_uilo_set_dirty(w, 0);
    }

    for (;;) {
        size_t best = nc;
        size_t j;

        for (j = 0; j < nc; j++) {
            if (!curs[j].alive) {
                continue;
            }
            if (best >= nc || cursor_before(&curs[j], &curs[best])) {
                best = j;
            }
        }
        if (best >= nc) {
            break;
        }
        emit_frag(e, &curs[best]);
        if (e->err) {
            return -1;
        }
        (void)cursor_advance(&curs[best]);
    }
    return 0;
}

int ta_draw_phase2_foreach_frag(ta_draw_scene_t *scene, ta_phase2_frag_fn fn,
                                void *ctx) {
    ta_p2_emit_t e;

    memset(&e, 0, sizeof(e));
    e.fn = fn;
    e.ctx = ctx;
    return run_merge(scene, &e);
}

int ta_draw_phase2(ta_draw_scene_t *scene, ta_phase2_push_t *out,
                   size_t out_cap) {
    ta_p2_emit_t e;

    if (scene == NULL || (out_cap > 0 && out == NULL)) {
        return -1;
    }
    memset(&e, 0, sizeof(e));
    e.out = out;
    e.out_cap = out_cap;
    if (run_merge(scene, &e) != 0) {
        return -1;
    }
    return (int)e.npush;
}
