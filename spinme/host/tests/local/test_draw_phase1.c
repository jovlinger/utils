/* phase1 bakes dirty L2R/viewport farthest-to-nearest (no LCD push). */
#include "ta_draw_phase1.h"
#include "ta_shape_l2r.h"
#include "ta_uilayout.h"
#include "ta_viewport.h"

#include <stdio.h>
#include <string.h>

static int failures;
static int checks;

#define CHECK(cond)                                                            \
    do {                                                                       \
        checks++;                                                              \
        if (!(cond)) {                                                         \
            failures++;                                                        \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__,   \
                    #cond);                                                    \
        }                                                                      \
    } while (0)

int main(void) {
    ta_pack66_t under_px[4];
    ta_pack66_t glyph_px;
    ta_pack66_t text_px[32];
    ta_shape_bitmap_t under;
    ta_shape_bitmap_t glyph;
    uint32_t pack[4];
    size_t nw;
    unsigned idxs[1];
    ta_shape_l2r_t text;
    ta_uilayout_t uilo[2];
    ta_draw_node_t nodes[1];
    ta_draw_scene_t scene;
    ta_phase1_opts_t opts;
    uint8_t r, g, b, a;

    glyph_px = ta_pack66_rgba(0x3f, 0, 0, 3);
    under_px[0] = ta_pack66_rgba(0, 0x3f, 0, 3);
    under_px[1] = under_px[0];
    under_px[2] = under_px[0];
    under_px[3] = under_px[0];

    memset(&under, 0, sizeof(under));
    under.tag = TA_SHAPE_TAG_BITMAP;
    under.w = 2;
    under.h = 2;
    under.dirty = 0;
    under.pixels = under_px;

    memset(&glyph, 0, sizeof(glyph));
    glyph.tag = TA_SHAPE_TAG_BITMAP;
    glyph.w = 1;
    glyph.h = 1;
    glyph.pixels = &glyph_px;

    idxs[0] = 2;
    CHECK(ta_shapepack_encode(pack, 4, &nw, idxs, 1, TA_PACK_TAG_3x10) == 0);
    memset(&text, 0, sizeof(text));
    text.tag = TA_SHAPE_TAG_L2R;
    text.dirty = 1;
    text.w = 2;
    text.h = 2;
    text.pack = pack;
    text.n_items = 1;
    text.pixels = text_px;
    memset(text_px, 0, sizeof(text_px));

    ta_shape_table_reset();
    CHECK(ta_shape_table_set(1, &under) == 0);
    CHECK(ta_shape_table_set(2, &glyph) == 0);
    CHECK(ta_shape_table_set(3, (ta_shape_bitmap_t *)(void *)&text) == 0);

    uilo[0] = ta_uilo_make(1, 0, 0, 1); /* under farthest */
    uilo[1] = ta_uilo_make(1, 0, 0, 3); /* text nearer */
    memset(nodes, 0, sizeof(nodes));
    memset(&scene, 0, sizeof(scene));
    scene.uilo = uilo;
    scene.n_uilo = 2;
    scene.nodes = nodes;
    scene.n_nodes = 0;

    opts.under_shape_idx = 1;
    CHECK(ta_draw_phase1(&scene, &opts) == 0);

    /* Under green at (0,0) then red glyph overwrites (0,0). */
    ta_unpack66(text_px[0], &r, &g, &b, &a);
    CHECK(r == 0x3f);
    CHECK(a == 3);
    ta_unpack66(text_px[1], &r, &g, &b, &a);
    CHECK(g == 0x3f); /* under remains at (1,0) */

    /* Still dirty (phase2 clears). */
    CHECK(text.dirty == 1);
    /* No panel-sized shadow buffer allocated -- only shape local pixels. */

    /* Base crop under a Viewport placed at (1,1): window gets the base
     * pixel there (blue), the child glyph lands at ox, and a wider child
     * wraps after TA_PHASE1_SCROLL_GAP. */
    {
        ta_pack66_t base_px[16];
        ta_pack66_t vp_px[2];
        ta_shape_bitmap_t base;
        ta_shape_viewport_t vp;
        ta_uilayout_t uilo2[2];
        int i;

        for (i = 0; i < 16; i++) {
            base_px[i] = ta_pack66_rgba(0, 0, 0x3f, 3);
        }
        memset(&base, 0, sizeof(base));
        base.tag = TA_SHAPE_TAG_BITMAP;
        base.w = 4;
        base.h = 4;
        base.pixels = base_px;
        /* Child: the 2x2 L2R from above (red glyph at (0,0), clear else). */
        text.dirty = 1;
        memset(&vp, 0, sizeof(vp));
        vp.tag = TA_SHAPE_TAG_VIEWPORT;
        vp.w = 1;
        vp.h = 2;
        vp.pixels = vp_px;
        vp.child_idx = 3;
        vp.dirty = 1;
        vp.ox = 1; /* child col 1 is clear -> base shows */
        CHECK(ta_shape_table_set(4, &base) == 0);
        CHECK(ta_shape_table_set(5, (ta_shape_bitmap_t *)(void *)&vp) == 0);
        uilo2[0] = ta_uilo_make(0, 0, 0, 4);
        uilo2[1] = ta_uilo_make(1, 1, 1, 5);
        scene.uilo = uilo2;
        scene.n_uilo = 2;
        memset(&opts, 0, sizeof(opts));
        opts.base_shape_idx = 4;
        CHECK(ta_draw_phase1(&scene, &opts) == 0);
        ta_unpack66(vp_px[0], &r, &g, &b, &a);
        CHECK(b == 0x3f && a == 3); /* base under, never transparent */
        CHECK(text.dirty == 0);     /* child rebuilt by the viewport bake */
        vp.ox = 0;
        vp.dirty = 1;
        CHECK(ta_draw_phase1(&scene, &opts) == 0);
        ta_unpack66(vp_px[0], &r, &g, &b, &a);
        CHECK(r == 0x3f && a == 3); /* glyph at ox=0 */
    }

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_draw_phase1: %d checks ok\n", checks);
    return 0;
}
