/* KV editor page lists records; fwd/back moves the selection. */
#include "ta_kv.h"
#include "ta_kv_editor.h"
#include "ta_shape_swap.h"
#include "ta_uilayout.h"

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

#define PANEL 16

int main(void) {
    ta_pack66_t base_px[PANEL * PANEL];
    ta_pack66_t ed_px[PANEL * PANEL];
    ta_shape_bitmap_t base;
    ta_kv_editor_t ed;
    ta_shape_swap_t swap;

    ta_kv_reset();
    CHECK(ta_kv_put("alpha", "one", 3) == TA_KV_OK);
    CHECK(ta_kv_put("beta", "two", 3) == TA_KV_OK);
    CHECK(ta_kv_count() == 2);
    {
        char k[32];
        size_t n;

        CHECK(ta_kv_key_at(0, k, sizeof(k), &n) == TA_KV_OK);
        CHECK(strcmp(k, "alpha") == 0);
        CHECK(ta_kv_key_at(1, k, sizeof(k), &n) == TA_KV_OK);
        CHECK(strcmp(k, "beta") == 0);
    }

    ta_kv_editor_reset(&ed);
    CHECK(ta_kv_editor_bind(&ed, ed_px, PANEL, PANEL) == 0);
    CHECK(ta_kv_editor_refresh(&ed) == 0);
    CHECK(strcmp(ta_kv_editor_key(&ed), "alpha") == 0);
    CHECK(strcmp(ta_kv_editor_val(&ed), "one") == 0);
    CHECK(ta_kv_editor_fwd(&ed) == 1);
    CHECK(strcmp(ta_kv_editor_key(&ed), "beta") == 0);
    CHECK(ta_kv_editor_fwd(&ed) == 0);
    CHECK(ta_kv_editor_back(&ed) == 1);
    CHECK(strcmp(ta_kv_editor_key(&ed), "beta") == 0);

    memset(base_px, 0, sizeof(base_px));
    memset(&base, 0, sizeof(base));
    base.tag = TA_SHAPE_TAG_BITMAP;
    base.w = PANEL;
    base.h = PANEL;
    base.pixels = base_px;
    ta_shape_table_reset();
    CHECK(ta_shape_table_set(900, &base) == 0);
    CHECK(ta_kv_editor_install_shape(&ed) == 0);
    CHECK(ta_shape_table_get(TA_KV_EDITOR_IDX) == &ed.panel);

    memset(&swap, 0, sizeof(swap));
    swap.tag = TA_SHAPE_TAG_SWAP;
    swap.n = 2;
    swap.active = 0;
    swap.child_idx[0] = 900;
    swap.child_idx[1] = TA_KV_EDITOR_IDX;
    CHECK(ta_shape_swap_bind(&swap) == 0);
    CHECK(swap.pixels == base_px);
    CHECK(ta_shape_swap_set_active(&swap, 1) == 0);
    CHECK(swap.pixels == ed_px);

    /* Edit: enter, rotary char, fwd caret, commit via put. */
    CHECK(ta_kv_editor_enter(&ed) == 0);
    CHECK(ta_kv_editor_editing(&ed));
    CHECK(ta_kv_editor_field(&ed) == TA_KV_EDITOR_FIELD_VAL);
    CHECK(ta_kv_editor_rotate(&ed, 1) == 0); /* advance charset from 't' */
    {
        char got[32];
        size_t n;

        CHECK(ta_kv_editor_commit(&ed) == 0);
        CHECK(!ta_kv_editor_editing(&ed));
        CHECK(ta_kv_get("beta", got, sizeof(got), &n) == TA_KV_OK);
        CHECK(n >= 1);
        CHECK(got[0] != 't' || strcmp(got, "two") != 0);
    }
    CHECK(ta_kv_editor_enter(&ed) == 0);
    CHECK(ta_kv_editor_fwd(&ed) == 1);
    CHECK(ta_kv_editor_char_pos(&ed) == 1);
    CHECK(ta_kv_editor_back(&ed) == 0);
    CHECK(ta_kv_editor_enter(&ed) == 0); /* toggle to KEY */
    CHECK(ta_kv_editor_field(&ed) == TA_KV_EDITOR_FIELD_KEY);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_kv_editor: %d checks ok\n", checks);
    return 0;
}
