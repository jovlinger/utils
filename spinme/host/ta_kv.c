#include "ta_kv.h"

#include <string.h>

/* One max-sized record per historical slot, plus the 4-byte head.
 * Unlinked holes are not reused yet, so the cap matches the old slot count.
 */
#define TA_KV_IMAGE_CAP                                                        \
    (TA_KV_IMAGE_HEAD_SIZE +                                                   \
     (TA_KV_SLOTS * (TA_KV_REC_HDR_SIZE + (TA_KV_KEY_MAX - 1) + TA_KV_VAL_MAX)))

static uint8_t g_img[TA_KV_IMAGE_CAP];
static size_t g_hw;

static int key_ok(const char *key) {
    size_t n;

    if (key == NULL || key[0] == '\0') {
        return 0;
    }
    n = strlen(key);
    return n > 0 && n < TA_KV_KEY_MAX;
}

static uint32_t rd32(size_t off) {
    return (uint32_t)g_img[off] | ((uint32_t)g_img[off + 1] << 8) |
           ((uint32_t)g_img[off + 2] << 16) | ((uint32_t)g_img[off + 3] << 24);
}

static void wr32(size_t off, uint32_t v) {
    g_img[off] = (uint8_t)(v & 0xffu);
    g_img[off + 1] = (uint8_t)((v >> 8) & 0xffu);
    g_img[off + 2] = (uint8_t)((v >> 16) & 0xffu);
    g_img[off + 3] = (uint8_t)((v >> 24) & 0xffu);
}

static uint16_t rd16(size_t off) {
    return (uint16_t)((uint16_t)g_img[off] | ((uint16_t)g_img[off + 1] << 8));
}

static void wr16(size_t off, uint16_t v) {
    g_img[off] = (uint8_t)(v & 0xffu);
    g_img[off + 1] = (uint8_t)((v >> 8) & 0xffu);
}

static size_t rec_size(uint16_t key_len, uint32_t blob_len) {
    return (size_t)TA_KV_REC_HDR_SIZE + (size_t)key_len + (size_t)blob_len;
}

static int rec_key_eq(size_t off, const char *key, size_t klen) {
    uint16_t rk;

    rk = rd16(off + 4);
    if ((size_t)rk != klen) {
        return 0;
    }
    return memcmp(g_img + off + TA_KV_REC_HDR_SIZE, key, klen) == 0;
}

/* Walk live list. *prev_next_off is the address of the uint32 that points at
 * *off (the head, or the previous record's next field).
 */
static int find_live(const char *key, size_t klen, size_t *off,
                     size_t *prev_next_off) {
    size_t prev;
    uint32_t cur;

    prev = 0;
    cur = rd32(0);
    while (cur != 0) {
        if ((size_t)cur + TA_KV_REC_HDR_SIZE > g_hw) {
            return 0;
        }
        if (rec_key_eq((size_t)cur, key, klen)) {
            *off = (size_t)cur;
            *prev_next_off = prev;
            return 1;
        }
        prev = (size_t)cur;
        cur = rd32((size_t)cur);
    }
    return 0;
}

static void unlink_at(size_t off, size_t prev_next_off) {
    uint32_t nxt;

    nxt = rd32(off);
    wr32(prev_next_off, nxt);
}

static ta_kv_status_t append_rec(const char *key, size_t klen, const void *src,
                                 size_t len) {
    size_t need;
    size_t off;
    size_t prev;
    uint32_t cur;

    need = rec_size((uint16_t)klen, (uint32_t)len);
    if (g_hw + need > TA_KV_IMAGE_CAP) {
        return TA_KV_FULL;
    }
    off = g_hw;
    wr32(off, 0);
    wr16(off + 4, (uint16_t)klen);
    wr32(off + 6, (uint32_t)len);
    memcpy(g_img + off + TA_KV_REC_HDR_SIZE, key, klen);
    if (len > 0) {
        memcpy(g_img + off + TA_KV_REC_HDR_SIZE + klen, src, len);
    }
    prev = 0;
    cur = rd32(0);
    while (cur != 0) {
        prev = (size_t)cur;
        cur = rd32((size_t)cur);
    }
    wr32(prev, (uint32_t)off);
    g_hw = off + need;
    return TA_KV_OK;
}

void ta_kv_reset(void) {
    memset(g_img, 0, sizeof(g_img));
    g_hw = TA_KV_IMAGE_HEAD_SIZE;
}

const uint8_t *ta_kv_image(size_t *out_len) {
    if (out_len != NULL) {
        *out_len = g_hw;
    }
    return g_img;
}

static int image_chain_ok(size_t len) {
    uint32_t cur;
    unsigned guard;

    if (len < TA_KV_IMAGE_HEAD_SIZE || len > TA_KV_IMAGE_CAP) {
        return 0;
    }
    cur = rd32(0);
    guard = 0;
    while (cur != 0) {
        uint16_t klen;
        uint32_t blen;
        size_t need;

        if (guard++ > TA_KV_SLOTS) {
            return 0;
        }
        if ((size_t)cur < TA_KV_IMAGE_HEAD_SIZE ||
            (size_t)cur + TA_KV_REC_HDR_SIZE > len) {
            return 0;
        }
        klen = rd16((size_t)cur + 4);
        blen = rd32((size_t)cur + 6);
        need = rec_size(klen, blen);
        if ((size_t)cur + need > len) {
            return 0;
        }
        cur = rd32((size_t)cur);
    }
    return 1;
}

ta_kv_status_t ta_kv_load_image(const uint8_t *src, size_t len) {
    if (src == NULL) {
        return TA_KV_BAD_ARG;
    }
    if (len < TA_KV_IMAGE_HEAD_SIZE || len > TA_KV_IMAGE_CAP) {
        return TA_KV_BAD_ARG;
    }
    memset(g_img, 0, sizeof(g_img));
    memcpy(g_img, src, len);
    g_hw = len;
    if (!image_chain_ok(len)) {
        ta_kv_reset();
        return TA_KV_BAD_ARG;
    }
    return TA_KV_OK;
}

void ta_kv_install_factory(void) {
    static const char roster[] = "Draw\nNet\n";
    static const char draw_blob[] = "draw-v1";
    static const char net_blob[] = "net-v1";

    ta_kv_reset();
    (void)ta_kv_put(TA_KV_KEY_ACTORS, roster, sizeof(roster) - 1);
    (void)ta_kv_put("Draw", draw_blob, sizeof(draw_blob) - 1);
    (void)ta_kv_put("Net", net_blob, sizeof(net_blob) - 1);
}

int ta_kv_has(const char *key) {
    size_t off;
    size_t prev;
    size_t klen;

    if (!key_ok(key)) {
        return 0;
    }
    klen = strlen(key);
    return find_live(key, klen, &off, &prev) ? 1 : 0;
}

ta_kv_status_t ta_kv_get_len(const char *key, size_t *out_len) {
    size_t off;
    size_t prev;
    size_t klen;

    if (!key_ok(key) || out_len == NULL) {
        return TA_KV_BAD_ARG;
    }
    klen = strlen(key);
    if (!find_live(key, klen, &off, &prev)) {
        return TA_KV_MISSING;
    }
    *out_len = (size_t)rd32(off + 6);
    return TA_KV_OK;
}

ta_kv_status_t ta_kv_get(const char *key, void *dst, size_t dst_cap,
                         size_t *out_len) {
    size_t off;
    size_t prev;
    size_t klen;
    uint32_t blen;

    if (!key_ok(key) || out_len == NULL) {
        return TA_KV_BAD_ARG;
    }
    klen = strlen(key);
    if (!find_live(key, klen, &off, &prev)) {
        return TA_KV_MISSING;
    }
    blen = rd32(off + 6);
    *out_len = (size_t)blen;
    if (dst_cap < (size_t)blen) {
        return TA_KV_TOO_SMALL;
    }
    if (blen > 0) {
        if (dst == NULL) {
            return TA_KV_BAD_ARG;
        }
        memcpy(dst, g_img + off + TA_KV_REC_HDR_SIZE + klen, (size_t)blen);
    }
    return TA_KV_OK;
}

ta_kv_status_t ta_kv_put(const char *key, const void *src, size_t len) {
    size_t off;
    size_t prev;
    size_t klen;
    uint32_t old_len;

    if (!key_ok(key) || len > TA_KV_VAL_MAX) {
        return TA_KV_BAD_ARG;
    }
    if (len > 0 && src == NULL) {
        return TA_KV_BAD_ARG;
    }
    klen = strlen(key);
    if (find_live(key, klen, &off, &prev)) {
        old_len = rd32(off + 6);
        if (len <= (size_t)old_len) {
            wr32(off + 6, (uint32_t)len);
            if (len > 0) {
                memcpy(g_img + off + TA_KV_REC_HDR_SIZE + klen, src, len);
            }
            return TA_KV_OK;
        }
        if (g_hw + rec_size((uint16_t)klen, (uint32_t)len) > TA_KV_IMAGE_CAP) {
            return TA_KV_FULL;
        }
        unlink_at(off, prev);
    }
    return append_rec(key, klen, src, len);
}

ta_kv_status_t ta_kv_delete(const char *key) {
    size_t off;
    size_t prev;
    size_t klen;

    if (!key_ok(key)) {
        return TA_KV_BAD_ARG;
    }
    klen = strlen(key);
    if (!find_live(key, klen, &off, &prev)) {
        return TA_KV_MISSING;
    }
    unlink_at(off, prev);
    return TA_KV_OK;
}

ta_kv_status_t ta_config_get_controller(char *dst, size_t dst_cap,
                                        size_t *out_len) {
    return ta_kv_get(TA_KV_KEY_CONTROLLER, dst, dst_cap, out_len);
}

ta_kv_status_t ta_config_put_controller(const char *name) {
    size_t n;

    if (name == NULL) {
        return TA_KV_BAD_ARG;
    }
    n = strlen(name);
    return ta_kv_put(TA_KV_KEY_CONTROLLER, name, n);
}
