#include "ta_kv.h"

#include "ta_runtime_cfg.h"

#include <string.h>

#define TA_KV_IMAGE_CAP                                                        \
    (TA_KV_IMAGE_HEAD_SIZE +                                                   \
     (TA_KV_SLOTS * (TA_KV_REC_PREFIX_SIZE + (TA_KV_KEY_MAX - 1) +              \
                     TA_KV_VALUEINFO_SIZE + TA_KV_VAL_MAX)))

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

static size_t value_nbytes(uint32_t valueinfo) {
    uint32_t t;
    uint32_t p;

    t = TA_KV_VINFO_TYPE(valueinfo);
    p = TA_KV_VINFO_PAYLOAD(valueinfo);
    if (t == TA_KV_VTYPE_BOOL || t == TA_KV_VTYPE_SMALLINT) {
        return 0;
    }
    if (t == TA_KV_VTYPE_INT32) {
        return 4;
    }
    if (t == TA_KV_VTYPE_STRING || t == TA_KV_VTYPE_BLOB) {
        return (size_t)p;
    }
    return 0;
}

static size_t entry_size(uint16_t key_len, uint32_t valueinfo) {
    return (size_t)TA_KV_REC_PREFIX_SIZE + (size_t)key_len +
           (size_t)TA_KV_VALUEINFO_SIZE + value_nbytes(valueinfo);
}

static size_t value_off(size_t off, uint16_t key_len) {
    return off + TA_KV_REC_PREFIX_SIZE + (size_t)key_len + TA_KV_VALUEINFO_SIZE;
}

static size_t valueinfo_off(size_t off, uint16_t key_len) {
    return off + TA_KV_REC_PREFIX_SIZE + (size_t)key_len;
}

static int key_cmp(const uint8_t *a, size_t alen, const char *b, size_t blen) {
    size_t n;
    int c;

    n = alen < blen ? alen : blen;
    c = memcmp(a, b, n);
    if (c != 0) {
        return c;
    }
    if (alen < blen) {
        return -1;
    }
    if (alen > blen) {
        return 1;
    }
    return 0;
}

static int rec_key_eq(size_t off, const char *key, size_t klen) {
    uint16_t rk;

    rk = rd16(off + 8);
    if ((size_t)rk != klen) {
        return 0;
    }
    return memcmp(g_img + off + TA_KV_REC_PREFIX_SIZE, key, klen) == 0;
}

static int find_live(const char *key, size_t klen, size_t *off,
                     size_t *prev_next_off) {
    size_t prev;
    uint32_t cur;

    prev = 0;
    cur = rd32(0);
    while (cur != 0) {
        if ((size_t)cur + TA_KV_REC_PREFIX_SIZE > g_hw) {
            return 0;
        }
        if (rec_key_eq((size_t)cur, key, klen)) {
            *off = (size_t)cur;
            *prev_next_off = prev;
            return 1;
        }
        prev = (size_t)cur + 4; /* address of this record's next field */
        cur = rd32((size_t)cur + 4);
    }
    return 0;
}

static void unlink_at(size_t off, size_t prev_next_off) {
    uint32_t nxt;

    nxt = rd32(off + 4);
    wr32(prev_next_off, nxt);
}

static int first_fit(size_t skip_off, size_t need, size_t *off_out) {
    size_t offs[TA_KV_SLOTS];
    size_t ends[TA_KV_SLOTS];
    size_t n;
    size_t i;
    size_t j;
    size_t cursor;
    uint32_t cur;

    n = 0;
    cur = rd32(0);
    while (cur != 0) {
        uint16_t klen;
        uint32_t elen;

        if (n >= TA_KV_SLOTS) {
            return 0;
        }
        if ((size_t)cur != skip_off) {
            elen = rd32((size_t)cur);
            klen = rd16((size_t)cur + 8);
            (void)klen;
            offs[n] = (size_t)cur;
            ends[n] = (size_t)cur + (size_t)elen;
            n++;
        }
        cur = rd32((size_t)cur + 4);
    }
    for (i = 1; i < n; i++) {
        size_t o;
        size_t e;

        o = offs[i];
        e = ends[i];
        j = i;
        while (j > 0 && offs[j - 1] > o) {
            offs[j] = offs[j - 1];
            ends[j] = ends[j - 1];
            j--;
        }
        offs[j] = o;
        ends[j] = e;
    }
    cursor = TA_KV_IMAGE_HEAD_SIZE;
    for (i = 0; i < n; i++) {
        if (offs[i] > cursor && offs[i] - cursor >= need) {
            *off_out = cursor;
            return 1;
        }
        if (ends[i] > cursor) {
            cursor = ends[i];
        }
    }
    if (cursor < g_hw && g_hw - cursor >= need) {
        *off_out = cursor;
        return 1;
    }
    if (g_hw + need <= TA_KV_IMAGE_CAP) {
        *off_out = g_hw;
        return 1;
    }
    return 0;
}

/* Insert allocated record at off into the sorted live chain. */
static void link_sorted(size_t off, const char *key, size_t klen) {
    size_t prev_next;
    uint32_t cur;

    prev_next = 0;
    cur = rd32(0);
    while (cur != 0) {
        uint16_t rk;
        int cmp;

        rk = rd16((size_t)cur + 8);
        cmp = key_cmp(g_img + (size_t)cur + TA_KV_REC_PREFIX_SIZE, (size_t)rk,
                      key, klen);
        if (cmp > 0) {
            wr32(off + 4, cur);
            wr32(prev_next, (uint32_t)off);
            return;
        }
        prev_next = (size_t)cur + 4;
        cur = rd32((size_t)cur + 4);
    }
    wr32(off + 4, 0);
    wr32(prev_next, (uint32_t)off);
}

static ta_kv_status_t write_entry(size_t off, const char *key, size_t klen,
                                  uint32_t valueinfo, const void *val,
                                  size_t vlen) {
    size_t need;

    need = entry_size((uint16_t)klen, valueinfo);
    if (value_nbytes(valueinfo) != vlen) {
        return TA_KV_BAD_ARG;
    }
    wr32(off, (uint32_t)need);
    wr32(off + 4, 0);
    wr16(off + 8, (uint16_t)klen);
    memcpy(g_img + off + TA_KV_REC_PREFIX_SIZE, key, klen);
    wr32(valueinfo_off(off, (uint16_t)klen), valueinfo);
    if (vlen > 0) {
        if (val == NULL) {
            return TA_KV_BAD_ARG;
        }
        memcpy(g_img + value_off(off, (uint16_t)klen), val, vlen);
    }
    return TA_KV_OK;
}

static ta_kv_status_t put_typed_fixed(const char *key, uint32_t valueinfo,
                                      const void *val, size_t vlen) {
    size_t off;
    size_t prev;
    size_t klen;
    size_t need;
    uint32_t saved_next;
    ta_kv_status_t st;

    if (!key_ok(key) || vlen > TA_KV_VAL_MAX) {
        return TA_KV_BAD_ARG;
    }
    if (value_nbytes(valueinfo) != vlen) {
        return TA_KV_BAD_ARG;
    }
    if (vlen > 0 && val == NULL) {
        return TA_KV_BAD_ARG;
    }
    klen = strlen(key);
    need = entry_size((uint16_t)klen, valueinfo);

    if (find_live(key, klen, &off, &prev)) {
        uint32_t old_elen;

        old_elen = rd32(off);
        saved_next = rd32(off + 4);
        if (need <= (size_t)old_elen) {
            st = write_entry(off, key, klen, valueinfo, val, vlen);
            if (st != TA_KV_OK) {
                return st;
            }
            wr32(off + 4, saved_next);
            return TA_KV_OK;
        }
        unlink_at(off, prev);
    }

    if (!first_fit(0, need, &off)) {
        return TA_KV_FULL;
    }
    st = write_entry(off, key, klen, valueinfo, val, vlen);
    if (st != TA_KV_OK) {
        return st;
    }
    link_sorted(off, key, klen);
    if (off + need > g_hw) {
        g_hw = off + need;
    }
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
    const char *prev_key;
    size_t prev_klen;

    if (len < TA_KV_IMAGE_HEAD_SIZE || len > TA_KV_IMAGE_CAP) {
        return 0;
    }
    cur = rd32(0);
    guard = 0;
    prev_key = NULL;
    prev_klen = 0;
    while (cur != 0) {
        uint16_t klen;
        uint32_t elen;
        uint32_t vi;
        size_t need;

        if (guard++ > TA_KV_SLOTS) {
            return 0;
        }
        if ((size_t)cur < TA_KV_IMAGE_HEAD_SIZE ||
            (size_t)cur + TA_KV_REC_PREFIX_SIZE > len) {
            return 0;
        }
        elen = rd32((size_t)cur);
        klen = rd16((size_t)cur + 8);
        if ((size_t)cur + TA_KV_REC_PREFIX_SIZE + (size_t)klen +
                TA_KV_VALUEINFO_SIZE >
            len) {
            return 0;
        }
        vi = rd32(valueinfo_off((size_t)cur, klen));
        need = entry_size(klen, vi);
        if (elen != (uint32_t)need || (size_t)cur + need > len) {
            return 0;
        }
        if (prev_key != NULL) {
            if (key_cmp((const uint8_t *)prev_key, prev_klen,
                        (const char *)(g_img + (size_t)cur +
                                       TA_KV_REC_PREFIX_SIZE),
                        (size_t)klen) >= 0) {
                return 0;
            }
        }
        prev_key = (const char *)(g_img + (size_t)cur + TA_KV_REC_PREFIX_SIZE);
        prev_klen = (size_t)klen;
        cur = rd32((size_t)cur + 4);
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
    static const char *const names[] = {"Draw", "Net"};
    static const char draw_blob[] = "draw-v1";
    static const char net_blob[] = "net-v1";

    ta_kv_reset();
    (void)ta_kv_set_roster(names, 2);
    (void)ta_kv_put_blob("Draw", draw_blob, sizeof(draw_blob) - 1);
    (void)ta_kv_put_blob("Net", net_blob, sizeof(net_blob) - 1);
    ta_runtime_cfg_put_factory();
}

ta_kv_status_t ta_kv_set_roster(const char *const *names, size_t n) {
    char buf[TA_KV_VAL_MAX];
    size_t used;
    size_t i;

    if (names == NULL && n > 0) {
        return TA_KV_BAD_ARG;
    }
    used = 0;
    for (i = 0; i < n; i++) {
        size_t klen;

        if (names[i] == NULL || names[i][0] == '\0') {
            return TA_KV_BAD_ARG;
        }
        klen = strlen(names[i]);
        if (used + klen + 1 > TA_KV_VAL_MAX) {
            return TA_KV_BAD_ARG;
        }
        memcpy(buf + used, names[i], klen);
        used += klen;
        buf[used++] = '\n';
    }
    return ta_kv_put_string(TA_KV_KEY_ACTORS, buf, used);
}

size_t ta_kv_roster_count(void) {
    char buf[TA_KV_VAL_MAX];
    size_t len;
    size_t i;
    size_t n;

    if (ta_kv_get(TA_KV_KEY_ACTORS, buf, sizeof(buf), &len) != TA_KV_OK) {
        return 0;
    }
    n = 0;
    i = 0;
    while (i < len) {
        if (buf[i] == '\n') {
            i++;
            continue;
        }
        n++;
        while (i < len && buf[i] != '\n') {
            i++;
        }
    }
    return n;
}

ta_kv_status_t ta_kv_roster_at(size_t index, char *dst, size_t dst_cap,
                               size_t *out_len) {
    char buf[TA_KV_VAL_MAX];
    size_t len;
    size_t i;
    size_t n;
    size_t start;

    if (out_len == NULL) {
        return TA_KV_BAD_ARG;
    }
    if (ta_kv_get(TA_KV_KEY_ACTORS, buf, sizeof(buf), &len) != TA_KV_OK) {
        return TA_KV_MISSING;
    }
    n = 0;
    i = 0;
    start = 0;
    while (i < len) {
        if (buf[i] == '\n') {
            i++;
            continue;
        }
        start = i;
        while (i < len && buf[i] != '\n') {
            i++;
        }
        if (n == index) {
            *out_len = i - start;
            if (dst_cap < *out_len) {
                return TA_KV_TOO_SMALL;
            }
            if (*out_len > 0) {
                if (dst == NULL) {
                    return TA_KV_BAD_ARG;
                }
                memcpy(dst, buf + start, *out_len);
            }
            return TA_KV_OK;
        }
        n++;
    }
    return TA_KV_MISSING;
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

static ta_kv_status_t peek_entry(const char *key, size_t *off_out,
                                 uint16_t *klen_out, uint32_t *vi_out) {
    size_t off;
    size_t prev;
    size_t klen;
    uint16_t rk;

    if (!key_ok(key)) {
        return TA_KV_BAD_ARG;
    }
    klen = strlen(key);
    if (!find_live(key, klen, &off, &prev)) {
        return TA_KV_MISSING;
    }
    rk = rd16(off + 8);
    if (off_out != NULL) {
        *off_out = off;
    }
    if (klen_out != NULL) {
        *klen_out = rk;
    }
    if (vi_out != NULL) {
        *vi_out = rd32(valueinfo_off(off, rk));
    }
    return TA_KV_OK;
}

ta_kv_status_t ta_kv_get_len(const char *key, size_t *out_len) {
    uint32_t vi;
    ta_kv_status_t st;

    if (out_len == NULL) {
        return TA_KV_BAD_ARG;
    }
    st = peek_entry(key, NULL, NULL, &vi);
    if (st != TA_KV_OK) {
        return st;
    }
    *out_len = value_nbytes(vi);
    return TA_KV_OK;
}

ta_kv_status_t ta_kv_get(const char *key, void *dst, size_t dst_cap,
                         size_t *out_len) {
    size_t off;
    uint16_t rk;
    uint32_t vi;
    size_t vlen;
    ta_kv_status_t st;

    if (out_len == NULL) {
        return TA_KV_BAD_ARG;
    }
    st = peek_entry(key, &off, &rk, &vi);
    if (st != TA_KV_OK) {
        return st;
    }
    vlen = value_nbytes(vi);
    *out_len = vlen;
    if (dst_cap < vlen) {
        return TA_KV_TOO_SMALL;
    }
    if (vlen > 0) {
        if (dst == NULL) {
            return TA_KV_BAD_ARG;
        }
        memcpy(dst, g_img + value_off(off, rk), vlen);
    }
    return TA_KV_OK;
}

ta_kv_status_t ta_kv_get_type(const char *key, uint32_t *out_type) {
    uint32_t vi;
    ta_kv_status_t st;

    if (out_type == NULL) {
        return TA_KV_BAD_ARG;
    }
    st = peek_entry(key, NULL, NULL, &vi);
    if (st != TA_KV_OK) {
        return st;
    }
    *out_type = TA_KV_VINFO_TYPE(vi);
    return TA_KV_OK;
}

ta_kv_status_t ta_kv_put(const char *key, const void *src, size_t len) {
    return ta_kv_put_blob(key, src, len);
}

ta_kv_status_t ta_kv_put_blob(const char *key, const void *src, size_t len) {
    uint32_t vi;

    if (len > 0x1fffffffu) {
        return TA_KV_BAD_ARG;
    }
    vi = TA_KV_VINFO_PACK(TA_KV_VTYPE_BLOB, (uint32_t)len);
    return put_typed_fixed(key, vi, src, len);
}

ta_kv_status_t ta_kv_put_string(const char *key, const char *s, size_t len) {
    uint32_t vi;

    if (len > 0x1fffffffu) {
        return TA_KV_BAD_ARG;
    }
    vi = TA_KV_VINFO_PACK(TA_KV_VTYPE_STRING, (uint32_t)len);
    return put_typed_fixed(key, vi, s, len);
}

ta_kv_status_t ta_kv_put_bool(const char *key, int value) {
    uint32_t vi;

    vi = TA_KV_VINFO_PACK(TA_KV_VTYPE_BOOL, value ? 1u : 0u);
    return put_typed_fixed(key, vi, NULL, 0);
}

ta_kv_status_t ta_kv_get_bool(const char *key, int *out_value) {
    uint32_t vi;
    ta_kv_status_t st;

    if (out_value == NULL) {
        return TA_KV_BAD_ARG;
    }
    st = peek_entry(key, NULL, NULL, &vi);
    if (st != TA_KV_OK) {
        return st;
    }
    if (TA_KV_VINFO_TYPE(vi) != TA_KV_VTYPE_BOOL) {
        return TA_KV_BAD_TYPE;
    }
    *out_value = (TA_KV_VINFO_PAYLOAD(vi) & 1u) ? 1 : 0;
    return TA_KV_OK;
}

ta_kv_status_t ta_kv_put_smallint(const char *key, int32_t value) {
    uint32_t payload;
    uint32_t vi;

    /* Store as 29-bit two's complement in payload. */
    payload = ((uint32_t)value) & 0x1fffffffu;
    vi = TA_KV_VINFO_PACK(TA_KV_VTYPE_SMALLINT, payload);
    return put_typed_fixed(key, vi, NULL, 0);
}

ta_kv_status_t ta_kv_get_smallint(const char *key, int32_t *out_value) {
    size_t off;
    size_t prev;
    size_t klen;
    uint16_t rk;
    uint32_t vi;
    uint32_t p;

    if (out_value == NULL || !key_ok(key)) {
        return TA_KV_BAD_ARG;
    }
    klen = strlen(key);
    if (!find_live(key, klen, &off, &prev)) {
        return TA_KV_MISSING;
    }
    rk = rd16(off + 8);
    vi = rd32(valueinfo_off(off, rk));
    if (TA_KV_VINFO_TYPE(vi) != TA_KV_VTYPE_SMALLINT) {
        return TA_KV_BAD_TYPE;
    }
    p = TA_KV_VINFO_PAYLOAD(vi);
    if (p & 0x10000000u) {
        *out_value = (int32_t)(p | 0xe0000000u);
    } else {
        *out_value = (int32_t)p;
    }
    return TA_KV_OK;
}

ta_kv_status_t ta_kv_put_i32(const char *key, int32_t value) {
    uint8_t buf[4];
    uint32_t vi;

    buf[0] = (uint8_t)((uint32_t)value & 0xffu);
    buf[1] = (uint8_t)(((uint32_t)value >> 8) & 0xffu);
    buf[2] = (uint8_t)(((uint32_t)value >> 16) & 0xffu);
    buf[3] = (uint8_t)(((uint32_t)value >> 24) & 0xffu);
    vi = TA_KV_VINFO_PACK(TA_KV_VTYPE_INT32, 0u);
    return put_typed_fixed(key, vi, buf, 4);
}

ta_kv_status_t ta_kv_get_i32(const char *key, int32_t *out_value) {
    size_t off;
    uint16_t rk;
    uint32_t vi;
    size_t vlen;
    const uint8_t *p;
    ta_kv_status_t st;

    if (out_value == NULL) {
        return TA_KV_BAD_ARG;
    }
    st = peek_entry(key, &off, &rk, &vi);
    if (st != TA_KV_OK) {
        return st;
    }
    vlen = value_nbytes(vi);
    if (TA_KV_VINFO_TYPE(vi) != TA_KV_VTYPE_INT32 || vlen != 4) {
        return TA_KV_BAD_TYPE;
    }
    p = g_img + value_off(off, rk);
    *out_value = (int32_t)((uint32_t)p[0] | ((uint32_t)p[1] << 8) |
                           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24));
    return TA_KV_OK;
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

size_t ta_kv_count(void) {
    size_t n;
    uint32_t cur;

    n = 0;
    cur = rd32(0);
    while (cur != 0) {
        n++;
        cur = rd32((size_t)cur + 4);
    }
    return n;
}

static int live_at(size_t index, size_t *off_out) {
    size_t n;
    uint32_t cur;

    n = 0;
    cur = rd32(0);
    while (cur != 0) {
        if (n == index) {
            *off_out = (size_t)cur;
            return 1;
        }
        n++;
        cur = rd32((size_t)cur + 4);
    }
    return 0;
}

ta_kv_status_t ta_kv_key_at(size_t index, char *dst, size_t dst_cap,
                            size_t *out_len) {
    size_t off;
    uint16_t klen;

    if (dst == NULL || out_len == NULL) {
        return TA_KV_BAD_ARG;
    }
    if (!live_at(index, &off)) {
        return TA_KV_MISSING;
    }
    klen = rd16(off + 8);
    *out_len = (size_t)klen;
    if (dst_cap < (size_t)klen + 1u) {
        return TA_KV_TOO_SMALL;
    }
    memcpy(dst, g_img + off + TA_KV_REC_PREFIX_SIZE, klen);
    dst[klen] = '\0';
    return TA_KV_OK;
}

ta_kv_status_t ta_kv_val_at(size_t index, void *dst, size_t dst_cap,
                            size_t *out_len) {
    size_t off;
    uint16_t klen;
    uint32_t vi;
    size_t vlen;

    if (out_len == NULL) {
        return TA_KV_BAD_ARG;
    }
    if (!live_at(index, &off)) {
        return TA_KV_MISSING;
    }
    klen = rd16(off + 8);
    vi = rd32(valueinfo_off(off, klen));
    vlen = value_nbytes(vi);
    *out_len = vlen;
    if (dst == NULL) {
        return TA_KV_BAD_ARG;
    }
    if (dst_cap < vlen) {
        return TA_KV_TOO_SMALL;
    }
    if (vlen > 0) {
        memcpy(dst, g_img + value_off(off, klen), vlen);
    }
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
    return ta_kv_put_string(TA_KV_KEY_CONTROLLER, name, n);
}
