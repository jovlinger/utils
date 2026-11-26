/* fn_enum wire: nav select and swap step without function pointers on shapes. */
#include "ta_shape_swap.h"
#include "ta_uilayout.h"
#include "ta_wire.h"

#include <stdio.h>
#include <string.h>

static int failures;
static int checks;
static int glyph_down;
static int selecting_on;

#define CHECK(cond)                                                            \
    do {                                                                       \
        checks++;                                                              \
        if (!(cond)) {                                                         \
            failures++;                                                        \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__,   \
                    #cond);                                                    \
        }                                                                      \
    } while (0)

static void on_glyph(int down) {
    glyph_down = down;
}

static void on_sel(int on) {
    selecting_on = on;
}

int main(void) {
    ta_pack66_t a[4], b[4];
    ta_shape_bitmap_t sa, sb;
    ta_shape_swap_t swap;
    ta_wire_ctx_t wire;

    memset(a, 0, sizeof(a));
    memset(b, 0, sizeof(b));
    sa.tag = TA_SHAPE_TAG_BITMAP;
    sa.w = 2;
    sa.h = 2;
    sa.pixels = a;
    sb.tag = TA_SHAPE_TAG_BITMAP;
    sb.w = 2;
    sb.h = 2;
    sb.pixels = b;
    ta_shape_table_reset();
    CHECK(ta_shape_table_set(1, &sa) == 0);
    CHECK(ta_shape_table_set(2, &sb) == 0);
    memset(&swap, 0, sizeof(swap));
    swap.tag = TA_SHAPE_TAG_SWAP;
    swap.n = 2;
    swap.active = 0;
    swap.child_idx[0] = 1;
    swap.child_idx[1] = 2;
    CHECK(ta_shape_swap_bind(&swap) == 0);

    memset(&wire, 0, sizeof(wire));
    wire.swap = &swap;
    wire.on_nav_glyph = on_glyph;
    wire.on_selecting = on_sel;
    ta_wire_reset(&wire);

    CHECK(ta_wire_touch(&wire, TA_FN_NAV, 1) == 0);
    CHECK(wire.selecting == 1);
    CHECK(glyph_down == 1);
    CHECK(selecting_on == 1);
    CHECK(ta_wire_rotary(&wire, TA_FN_SWAP_STEP, 1, 1) == 0);
    CHECK(swap.active == 1);
    CHECK(ta_wire_touch(&wire, TA_FN_NAV, 1) == 0);
    CHECK(wire.selecting == 0);
    CHECK(glyph_down == 0);
    CHECK(selecting_on == 0);
    CHECK(swap.active == 1);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_wire: %d checks ok\n", checks);
    return 0;
}
