#include "ta_kv_editor.h"

#include "ta_kv.h"

#include <stdio.h>
#include <string.h>

static void init_charset(ta_kv_editor_t *ed) {
    size_t i;
    size_t n = 0;

    /* Space then printable ASCII for rotary pick. */
    ed->charset[n++] = ' ';
    for (i = 33; i <= 126; i++) {
        ed->charset[n++] = (char)i;
    }
    ed->charset_n = n;
}

static char *active_field(ta_kv_editor_t *ed) {
    return ed->field == TA_KV_EDITOR_FIELD_KEY ? ed->key : ed->val;
}

static size_t field_len(const ta_kv_editor_t *ed) {
    const char *s =
        ed->field == TA_KV_EDITOR_FIELD_KEY ? ed->key : ed->val;
    return strlen(s);
}

static void sync_char_sel(ta_kv_editor_t *ed) {
    char *s;
    size_t len;
    size_t i;
    char ch;

    s = active_field(ed);
    len = strlen(s);
    if (ed->char_pos > len) {
        ed->char_pos = (unsigned)len;
    }
    ch = ed->char_pos < len ? s[ed->char_pos] : ' ';
    ed->char_sel = 0;
    for (i = 0; i < ed->charset_n; i++) {
        if (ed->charset[i] == ch) {
            ed->char_sel = (unsigned)i;
            break;
        }
    }
}

void ta_kv_editor_reset(ta_kv_editor_t *ed) {
    if (ed == NULL) {
        return;
    }
    memset(ed, 0, sizeof(*ed));
}

int ta_kv_editor_bind(ta_kv_editor_t *ed, ta_pack66_t *pixels, uint16_t w,
                      uint16_t h) {
    if (ed == NULL || pixels == NULL || w == 0 || h == 0) {
        return -1;
    }
    ed->pixels = pixels;
    ed->panel_w = w;
    ed->panel_h = h;
    ed->cursor = 0;
    ed->key[0] = '\0';
    ed->val[0] = '\0';
    ed->ready = 1;
    ed->editing = 0;
    ed->field = TA_KV_EDITOR_FIELD_VAL;
    ed->char_pos = 0;
    ed->char_sel = 0;
    init_charset(ed);
    memset(&ed->panel, 0, sizeof(ed->panel));
    ed->panel.tag = TA_SHAPE_TAG_BITMAP;
    ed->panel.w = w;
    ed->panel.h = h;
    ed->panel.pixels = pixels;
    ed->panel.dirty = 1;
    return 0;
}

static void fill_view(ta_kv_editor_t *ed) {
    size_t n;
    size_t i;
    ta_pack66_t bg;
    ta_pack66_t mark;

    n = (size_t)ed->panel_w * (size_t)ed->panel_h;
    bg = ta_pack66_rgba(2, 2, 4, 3);
    mark = ta_pack66_rgba(40, 40, 10, 3);
    for (i = 0; i < n; i++) {
        ed->pixels[i] = bg;
    }
    /* Cursor fingerprint in the first row so paint tests can see the page. */
    if (ed->panel_w > 0) {
        ed->pixels[ed->cursor % ed->panel_w] = mark;
    }
    ed->panel.dirty = 1;
}

int ta_kv_editor_refresh(ta_kv_editor_t *ed) {
    size_t n;
    size_t klen;
    size_t vlen;
    char vbuf[TA_KV_VAL_MAX];
    ta_kv_status_t st;

    if (ed == NULL || !ed->ready) {
        return -1;
    }
    n = ta_kv_count();
    ed->key[0] = '\0';
    ed->val[0] = '\0';
    if (n == 0) {
        snprintf(ed->key, sizeof(ed->key), "(empty)");
        fill_view(ed);
        return 0;
    }
    if (ed->cursor >= n) {
        ed->cursor = 0;
    }
    st = ta_kv_key_at(ed->cursor, ed->key, sizeof(ed->key), &klen);
    if (st != TA_KV_OK) {
        return -1;
    }
    st = ta_kv_val_at(ed->cursor, vbuf, sizeof(vbuf), &vlen);
    if (st != TA_KV_OK) {
        return -1;
    }
    if (vlen >= sizeof(ed->val)) {
        vlen = sizeof(ed->val) - 1;
    }
    memcpy(ed->val, vbuf, vlen);
    ed->val[vlen] = '\0';
    /* Prefer printable preview; binary blobs show length. */
    {
        size_t i;
        int ascii = 1;

        for (i = 0; i < vlen; i++) {
            unsigned char c = (unsigned char)ed->val[i];

            if (c < 32 || c > 126) {
                ascii = 0;
                break;
            }
        }
        if (!ascii) {
            snprintf(ed->val, sizeof(ed->val), "<%zu bytes>", vlen);
        }
    }
    fill_view(ed);
    return 0;
}

unsigned ta_kv_editor_fwd(ta_kv_editor_t *ed) {
    size_t n;
    size_t len;

    if (ed == NULL || !ed->ready) {
        return 0;
    }
    if (ed->editing) {
        len = field_len(ed);
        if (ed->char_pos < len) {
            ed->char_pos++;
        } else if (len + 1 < TA_KV_EDITOR_LINE) {
            /* Grow one space at the end so rotary can fill it. */
            active_field(ed)[len] = ' ';
            active_field(ed)[len + 1] = '\0';
            ed->char_pos = (unsigned)len;
        }
        sync_char_sel(ed);
        fill_view(ed);
        return ed->char_pos;
    }
    n = ta_kv_count();
    if (n == 0) {
        ed->cursor = 0;
    } else {
        ed->cursor = (ed->cursor + 1) % (unsigned)n;
    }
    (void)ta_kv_editor_refresh(ed);
    return ed->cursor;
}

unsigned ta_kv_editor_back(ta_kv_editor_t *ed) {
    size_t n;

    if (ed == NULL || !ed->ready) {
        return 0;
    }
    if (ed->editing) {
        if (ed->char_pos > 0) {
            ed->char_pos--;
        }
        sync_char_sel(ed);
        fill_view(ed);
        return ed->char_pos;
    }
    n = ta_kv_count();
    if (n == 0) {
        ed->cursor = 0;
    } else if (ed->cursor == 0) {
        ed->cursor = (unsigned)n - 1;
    } else {
        ed->cursor--;
    }
    (void)ta_kv_editor_refresh(ed);
    return ed->cursor;
}

int ta_kv_editor_enter(ta_kv_editor_t *ed) {
    if (ed == NULL || !ed->ready) {
        return -1;
    }
    if (!ed->editing) {
        ed->editing = 1;
        ed->field = TA_KV_EDITOR_FIELD_VAL;
        ed->char_pos = 0;
        sync_char_sel(ed);
        fill_view(ed);
        return 0;
    }
    /* Toggle KEY <-> VAL while editing. */
    ed->field = ed->field == TA_KV_EDITOR_FIELD_VAL ? TA_KV_EDITOR_FIELD_KEY
                                                    : TA_KV_EDITOR_FIELD_VAL;
    ed->char_pos = 0;
    sync_char_sel(ed);
    fill_view(ed);
    return 0;
}

int ta_kv_editor_rotate(ta_kv_editor_t *ed, int8_t steps) {
    char *s;
    size_t len;
    int sel;

    if (ed == NULL || !ed->ready || !ed->editing || ed->charset_n == 0) {
        return -1;
    }
    if (steps == 0) {
        return 0;
    }
    sel = (int)ed->char_sel + (int)steps;
    while (sel < 0) {
        sel += (int)ed->charset_n;
    }
    sel %= (int)ed->charset_n;
    ed->char_sel = (unsigned)sel;
    s = active_field(ed);
    len = strlen(s);
    if (ed->char_pos < len) {
        s[ed->char_pos] = ed->charset[ed->char_sel];
    } else if (len + 1 < TA_KV_EDITOR_LINE) {
        s[len] = ed->charset[ed->char_sel];
        s[len + 1] = '\0';
        ed->char_pos = (unsigned)len;
    }
    fill_view(ed);
    return 0;
}

int ta_kv_editor_commit(ta_kv_editor_t *ed) {
    size_t vlen;
    ta_kv_status_t st;

    if (ed == NULL || !ed->ready || !ed->editing) {
        return -1;
    }
    if (ed->key[0] == '\0') {
        return -1;
    }
    /* Trim trailing spaces grown for caret. */
    vlen = strlen(ed->val);
    while (vlen > 0 && ed->val[vlen - 1] == ' ') {
        vlen--;
    }
    ed->val[vlen] = '\0';
    st = ta_kv_put(ed->key, ed->val, vlen);
    if (st != TA_KV_OK) {
        return -1;
    }
    ed->editing = 0;
    ed->char_pos = 0;
    return ta_kv_editor_refresh(ed);
}

int ta_kv_editor_editing(const ta_kv_editor_t *ed) {
    return ed != NULL && ed->editing;
}

unsigned ta_kv_editor_field(const ta_kv_editor_t *ed) {
    return ed == NULL ? 0 : ed->field;
}

unsigned ta_kv_editor_char_pos(const ta_kv_editor_t *ed) {
    return ed == NULL ? 0 : ed->char_pos;
}

unsigned ta_kv_editor_cursor(const ta_kv_editor_t *ed) {
    return ed == NULL ? 0 : ed->cursor;
}

const char *ta_kv_editor_key(const ta_kv_editor_t *ed) {
    return ed == NULL ? "" : ed->key;
}

const char *ta_kv_editor_val(const ta_kv_editor_t *ed) {
    return ed == NULL ? "" : ed->val;
}

int ta_kv_editor_install_shape(ta_kv_editor_t *ed) {
    if (ed == NULL || !ed->ready) {
        return -1;
    }
    return ta_shape_table_set(TA_KV_EDITOR_IDX, &ed->panel);
}
