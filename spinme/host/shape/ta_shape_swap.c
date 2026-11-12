#include "ta_shape_swap.h"

static int child_bitmap(unsigned idx, ta_shape_bitmap_t **out) {
    ta_shape_bitmap_t *hdr;

    hdr = ta_shape_table_get(idx);
    if (hdr == NULL || hdr->pixels == NULL || hdr->w == 0 || hdr->h == 0) {
        return -1;
    }
    /* Bitmap-layout header (tag BITMAP / L2R / VIEWPORT / SWAP all share
     * tag/dirty/w/h/pixels prefix). */
    *out = hdr;
    return 0;
}

int ta_shape_swap_bind(ta_shape_swap_t *swap) {
    ta_shape_bitmap_t *first;
    unsigned i;

    if (swap == NULL || swap->tag != TA_SHAPE_TAG_SWAP) {
        return -1;
    }
    if (swap->n == 0 || swap->n > TA_SWAP_MAX || swap->active >= swap->n) {
        return -1;
    }
    if (child_bitmap(swap->child_idx[0], &first) != 0) {
        return -1;
    }
    for (i = 1; i < swap->n; i++) {
        ta_shape_bitmap_t *ch;

        if (child_bitmap(swap->child_idx[i], &ch) != 0) {
            return -1;
        }
        if (ch->w != first->w || ch->h != first->h) {
            return -1;
        }
    }
    if (child_bitmap(swap->child_idx[swap->active], &first) != 0) {
        return -1;
    }
    swap->w = first->w;
    swap->h = first->h;
    swap->pixels = first->pixels;
    return 0;
}

int ta_shape_swap_set_active(ta_shape_swap_t *swap, unsigned active) {
    if (swap == NULL || swap->tag != TA_SHAPE_TAG_SWAP || active >= swap->n) {
        return -1;
    }
    swap->active = active;
    swap->dirty = 1;
    return ta_shape_swap_bind(swap);
}

unsigned ta_shape_swap_active_idx(const ta_shape_swap_t *swap) {
    if (swap == NULL || swap->n == 0 || swap->active >= swap->n) {
        return 0;
    }
    return swap->child_idx[swap->active];
}
