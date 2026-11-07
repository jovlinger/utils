#include "ta_draw_glass.h"

#include "ta_chrome_icons.h"
#include "ta_draw_phase1.h"
#include "ta_draw_update.h"
#include "ta_hit_dispatch.h"
#include "ta_shape_l2r.h"
#include "ta_shape_swap.h"
#include "ta_viewport.h"

#include <stdio.h>
#include <string.h>

/* Text slots (icons cover transport + nav). */
enum {
    TS_ZONE = 0,
    TS_ARTIST = 1,
    TS_ALBUM = 2,
    TS_TITLE = 3, /* viewport child */
    TS_VOLUME = 4,
    TS_CLOCK = 5,
    TS_N = 6
};

static const unsigned k_ts_idx[TS_N] = {
    TA_GLASS_IDX_ZONE,      TA_GLASS_IDX_ARTIST, TA_GLASS_IDX_ALBUM,
    TA_GLASS_IDX_TITLE_L2R, TA_GLASS_IDX_VOLUME, TA_GLASS_IDX_CLOCK};

/* Follow slot that shows each text slot (title shows through the viewport). */
static const unsigned k_ts_follow[TS_N] = {
    TA_FOLLOW_ZONE,   TA_FOLLOW_ARTIST, TA_FOLLOW_ALBUM,
    TA_FOLLOW_TITLE,  TA_FOLLOW_VOLUME, TA_FOLLOW_CLOCK};

typedef struct text_slot {
    ta_shape_l2r_t l2r;
    uint32_t pack[TA_GLASS_PACK_WORDS];
    int8_t kern[TA_GLASS_TEXT_MAX + 1];
    ta_pack66_t *px;
    size_t px_cap;
    uint16_t cap_w;
    char text[TA_GLASS_TEXT_MAX + 1];
} text_slot_t;

typedef struct glass_state {
    const ta_glass_backend_t *be;
    ta_glass_cfg_t cfg;
    int have_cfg;
    int installed;
    int lit;
    unsigned idle_s;
    unsigned uptime_s;
    ta_shape_bitmap_t base;
    ta_shape_viewport_t title_vp;
    ta_shape_swap_t swap;
    ta_shape_bitmap_t transport_icon;
    ta_shape_bitmap_t nav_icon;
    ta_pack66_t transport_px[TA_CHROME_ICON_PX * TA_CHROME_ICON_PX];
    ta_pack66_t nav_px[TA_CHROME_ICON_PX * TA_CHROME_ICON_PX];
    int nav_down; /* 0 = up arrow, 1 = down arrow (selecting) */
    int transport_playing_drawn; /* -1 unknown; tracks icon cache */
    text_slot_t ts[TS_N];
    ta_follow_chrome_t chrome;
    ta_draw_scene_t scene;
    ta_draw_node_t nodes[TA_FOLLOW_N];
    uint8_t polled;
    uint8_t desired;
    uint8_t playing;
    ta_glass_stats_t st;
} glass_state_t;

static glass_state_t g;

void ta_glass_reset(void) {
    memset(&g, 0, sizeof(g));
    g.lit = 1;
    g.polled = TA_GLASS_UNKNOWN;
    g.desired = TA_GLASS_UNKNOWN;
    g.playing = TA_GLASS_UNKNOWN;
    g.transport_playing_drawn = -1;
}

void ta_glass_set_backend(const ta_glass_backend_t *b) {
    g.be = b;
}

void ta_glass_set_cfg(const ta_glass_cfg_t *c) {
    if (c == NULL) {
        g.have_cfg = 0;
        return;
    }
    g.cfg = *c;
    g.have_cfg = 1;
}

const ta_glass_stats_t *ta_glass_stats(void) {
    return &g.st;
}

int ta_glass_installed(void) {
    return g.installed;
}

int ta_glass_backlight(void) {
    return g.lit;
}

int ta_glass_polled(void) {
    return g.polled == TA_GLASS_UNKNOWN ? -1 : (int)g.polled;
}

int ta_glass_desired(void) {
    return g.desired == TA_GLASS_UNKNOWN ? -1 : (int)g.desired;
}

int ta_glass_playing(void) {
    return g.playing == TA_GLASS_UNKNOWN ? -1 : (int)g.playing;
}

const ta_follow_chrome_t *ta_glass_chrome(void) {
    return &g.chrome;
}

const char *ta_glass_text(uint8_t field) {
    switch (field) {
    case TA_DRAW_TEXT_ZONE:
        return g.ts[TS_ZONE].text;
    case TA_DRAW_TEXT_ARTIST:
        return g.ts[TS_ARTIST].text;
    case TA_DRAW_TEXT_ALBUM:
        return g.ts[TS_ALBUM].text;
    case TA_DRAW_TEXT_TITLE:
        return g.ts[TS_TITLE].text;
    default:
        return "";
    }
}

/* ---- dirty bookkeeping ------------------------------------------------- */

static void mark_follow_dirty(unsigned follow_slot) {
    ta_shape_bitmap_t *hdr;

    if (follow_slot >= g.chrome.n) {
        return;
    }
    hdr = ta_shape_table_get(ta_uilo_shape(g.chrome.uilo[follow_slot]));
    if (hdr != NULL) {
        hdr->dirty = 1;
    }
    g.chrome.uilo[follow_slot] = ta_uilo_set_dirty(g.chrome.uilo[follow_slot], 1);
}

static void mark_all_dirty(void) {
    size_t i;

    for (i = 0; i < g.chrome.n; i++) {
        mark_follow_dirty((unsigned)i);
    }
    g.ts[TS_TITLE].l2r.dirty = 1;
}

void ta_glass_base_dirty(void) {
    if (!g.installed) {
        return;
    }
    /* Naive z+ policy (PLAN): a dirty base dirties everything above it. */
    mark_all_dirty();
}

/* ---- text construction ------------------------------------------------- */

static int glyph_ok(char ch) {
    if (g.cfg.glyphs == NULL || ch < 32 || ch > 126) {
        return 0;
    }
    return g.cfg.glyphs->idx[(unsigned)(ch - 32)] != 0;
}

/* Keep pixels; install an empty definition of width 1. */
static void set_empty_def(text_slot_t *s) {
    ta_pack66_t *px = s->l2r.pixels;

    s->pack[0] = 0;
    s->l2r.tag = TA_SHAPE_TAG_L2R;
    s->l2r.pack = s->pack;
    s->l2r.kernings = s->kern;
    s->l2r.n_items = 0;
    s->l2r.w = 1;
    s->l2r.h = g.cfg.text_h;
    s->l2r.pixels = px;
    s->l2r.dirty = 1;
}

/* Sanitize + clip ascii into the slot's L2R; pixels pointer preserved. */
static int build_text(text_slot_t *s, const char *ascii) {
    char buf[TA_GLASS_TEXT_MAX + 1];
    size_t n = 0;
    size_t i;
    ta_pack66_t *px = s->l2r.pixels;

    for (i = 0; ascii != NULL && ascii[i] != '\0' && n < TA_GLASS_TEXT_MAX;
         i++) {
        char ch = ascii[i];

        if (glyph_ok(ch)) {
            buf[n++] = ch;
        } else if (glyph_ok('?')) {
            buf[n++] = '?';
        }
    }
    buf[n] = '\0';
    for (;;) {
        ta_shape_l2r_t tmp;

        if (n == 0) {
            set_empty_def(s);
            s->l2r.pixels = px;
            return 0;
        }
        if (ta_text_build(&tmp, buf, g.cfg.glyphs, g.cfg.kern_table, s->pack,
                          TA_GLASS_PACK_WORDS, s->kern,
                          TA_GLASS_TEXT_MAX + 1) == 0 &&
            tmp.w <= s->cap_w && tmp.h <= g.cfg.text_h &&
            (size_t)tmp.w * (size_t)tmp.h <= s->px_cap) {
            s->l2r = tmp;
            s->l2r.pixels = px;
            s->l2r.dirty = 1;
            return 0;
        }
        /* Too wide (or unbuildable): drop the last char and retry. */
        buf[--n] = '\0';
    }
}

static int slot_set_text(int ts, const char *ascii) {
    text_slot_t *s = &g.ts[ts];
    size_t len;

    if (ascii == NULL) {
        ascii = "";
    }
    len = strlen(ascii);
    if (len > TA_GLASS_TEXT_MAX) {
        len = TA_GLASS_TEXT_MAX;
    }
    if (strncmp(s->text, ascii, len) == 0 && s->text[len] == '\0') {
        return 0; /* unchanged: no dirty churn */
    }
    memcpy(s->text, ascii, len);
    s->text[len] = '\0';
    if (!g.installed) {
        return 0;
    }
    if (build_text(s, s->text) != 0) {
        g.st.errors++;
        return -1;
    }
    if (ts == TS_TITLE) {
        g.title_vp.ox = 0;
        g.title_vp.oy = 0;
        g.title_vp.dirty = 1;
    }
    mark_follow_dirty(k_ts_follow[ts]);
    return 0;
}

int ta_glass_set_text(uint8_t field, const char *ascii) {
    int rc;

    switch (field) {
    case TA_DRAW_TEXT_ZONE:
        rc = slot_set_text(TS_ZONE, ascii);
        break;
    case TA_DRAW_TEXT_ARTIST:
        rc = slot_set_text(TS_ARTIST, ascii);
        break;
    case TA_DRAW_TEXT_ALBUM:
        rc = slot_set_text(TS_ALBUM, ascii);
        break;
    case TA_DRAW_TEXT_TITLE:
        rc = slot_set_text(TS_TITLE, ascii);
        break;
    default:
        return -1;
    }
    if (rc == 0) {
        g.st.text_sets++;
    }
    return rc;
}

static void represent_transport_icon(int force) {
    if (!force && g.transport_playing_drawn == (int)g.playing && g.installed) {
        return;
    }
    g.transport_playing_drawn = (int)g.playing;
    if (g.playing == 1) {
        ta_chrome_icon_pause_outline(g.transport_px, TA_CHROME_ICON_PX);
    } else {
        ta_chrome_icon_play_outline(g.transport_px, TA_CHROME_ICON_PX);
    }
    g.transport_icon.dirty = 1;
    if (g.installed) {
        mark_follow_dirty(TA_FOLLOW_TRANSPORT);
    }
}

static void represent_nav_icon(void) {
    if (g.nav_down) {
        ta_chrome_icon_down_solid(g.nav_px, TA_CHROME_ICON_PX);
    } else {
        ta_chrome_icon_up_solid(g.nav_px, TA_CHROME_ICON_PX);
    }
    g.nav_icon.dirty = 1;
    mark_follow_dirty(TA_FOLLOW_NAV);
}

static void represent_status(void) {
    char vol[8];
    uint8_t shown = g.polled;

    if (g.desired != TA_GLASS_UNKNOWN && g.desired != g.polled) {
        shown = g.desired; /* pending knob value leads the glass */
    }
    if (shown == TA_GLASS_UNKNOWN) {
        strcpy(vol, "---");
    } else {
        snprintf(vol, sizeof(vol), "%u", (unsigned)shown);
    }
    (void)slot_set_text(TS_VOLUME, vol);
    represent_transport_icon(0);
}

void ta_glass_set_status(uint8_t polled, uint8_t desired, uint8_t playing) {
    if (polled != TA_GLASS_UNKNOWN) {
        g.polled = polled > 100 ? 100 : polled;
    }
    if (desired != TA_GLASS_UNKNOWN) {
        g.desired = desired > 100 ? 100 : desired;
    }
    if (playing != TA_GLASS_UNKNOWN) {
        g.playing = playing ? 1 : 0;
    }
    g.st.status_sets++;
    represent_status();
}

/* ---- install ----------------------------------------------------------- */

static int alloc_slot(text_slot_t *s, uint16_t cap_w) {
    s->cap_w = cap_w;
    s->px_cap = (size_t)cap_w * (size_t)g.cfg.text_h;
    if (s->px == NULL) {
        s->px = g.be->alloc_px(s->px_cap);
    }
    if (s->px == NULL) {
        return -1;
    }
    memset(s->px, 0, s->px_cap * sizeof(ta_pack66_t));
    s->l2r.pixels = s->px;
    return 0;
}

int ta_glass_install_stack(void) {
    unsigned shape_idx[TA_FOLLOW_N];
    ta_follow_metrics_t m;
    size_t i;

    if (g.be == NULL || g.be->alloc_px == NULL || g.be->push_rect == NULL ||
        !g.have_cfg || g.cfg.glyphs == NULL || g.cfg.text_h == 0 ||
        g.cfg.view_w == 0) {
        g.st.errors++;
        return -1;
    }
    /* Shapes into the table (glyph bitmaps are the glue's entries). */
    memset(&g.base, 0, sizeof(g.base));
    g.base.tag = TA_SHAPE_TAG_BITMAP;
    g.base.w = g.cfg.panel_w;
    g.base.h = g.cfg.panel_h;
    g.base.pixels = g.cfg.base_pixels;
    g.base.dirty = 1;
    if (ta_shape_table_set(TA_GLASS_IDX_BASE, &g.base) != 0) {
        return -1;
    }
    /* SwapShape root: child 0 is the follow page (base stand-in size; the
     * multi-layer chrome still paints when page==0). Later pages are
     * full-panel children added via ta_glass_add_page. */
    memset(&g.swap, 0, sizeof(g.swap));
    g.swap.tag = TA_SHAPE_TAG_SWAP;
    g.swap.dirty = 1;
    g.swap.n = 1;
    g.swap.active = 0;
    g.swap.child_idx[0] = TA_GLASS_IDX_BASE;
    if (ta_shape_swap_bind(&g.swap) != 0) {
        return -1;
    }
    if (ta_shape_table_set(TA_GLASS_IDX_SWAP,
                           (ta_shape_bitmap_t *)(void *)&g.swap) != 0) {
        return -1;
    }
    for (i = 0; i < TS_N; i++) {
        uint16_t cap_w = i == TS_TITLE ? (uint16_t)TA_GLASS_LINE_W_MAX
                                       : g.cfg.view_w;
        if (alloc_slot(&g.ts[i], cap_w) != 0) {
            g.st.errors++;
            return -1;
        }
        set_empty_def(&g.ts[i]);
        if (ta_shape_table_set(k_ts_idx[i],
                               (ta_shape_bitmap_t *)(void *)&g.ts[i].l2r) != 0) {
            return -1;
        }
    }
    memset(&g.title_vp, 0, sizeof(g.title_vp));
    g.title_vp.tag = TA_SHAPE_TAG_VIEWPORT;
    g.title_vp.w = g.cfg.view_w;
    g.title_vp.h = g.cfg.text_h;
    g.title_vp.child_idx = TA_GLASS_IDX_TITLE_L2R;
    g.title_vp.pixels = g.be->alloc_px((size_t)g.cfg.view_w * g.cfg.text_h);
    if (g.title_vp.pixels == NULL) {
        g.st.errors++;
        return -1;
    }
    g.title_vp.dirty = 1;
    if (ta_shape_table_set(TA_GLASS_IDX_TITLE_VP,
                           (ta_shape_bitmap_t *)(void *)&g.title_vp) != 0) {
        return -1;
    }

    memset(&g.transport_icon, 0, sizeof(g.transport_icon));
    g.transport_icon.tag = TA_SHAPE_TAG_BITMAP;
    g.transport_icon.w = TA_CHROME_ICON_PX;
    g.transport_icon.h = TA_CHROME_ICON_PX;
    g.transport_icon.pixels = g.transport_px;
    g.transport_icon.dirty = 1;
    memset(&g.nav_icon, 0, sizeof(g.nav_icon));
    g.nav_icon.tag = TA_SHAPE_TAG_BITMAP;
    g.nav_icon.w = TA_CHROME_ICON_PX;
    g.nav_icon.h = TA_CHROME_ICON_PX;
    g.nav_icon.pixels = g.nav_px;
    g.nav_icon.dirty = 1;
    if (ta_shape_table_set(TA_GLASS_IDX_TRANSPORT, &g.transport_icon) != 0 ||
        ta_shape_table_set(TA_GLASS_IDX_NAV, &g.nav_icon) != 0) {
        return -1;
    }

    g.installed = 1;
    /* Definitions from current state (texts survive a re-install). */
    for (i = 0; i < TS_N; i++) {
        if (build_text(&g.ts[i], g.ts[i].text) != 0) {
            g.st.errors++;
            return -1;
        }
    }
    if (g.ts[TS_ZONE].text[0] == '\0') {
        (void)slot_set_text(TS_ZONE, "spinme");
    }
    if (g.ts[TS_CLOCK].text[0] == '\0') {
        (void)slot_set_text(TS_CLOCK, "00:00:00");
    }
    represent_status();
    represent_transport_icon(1);
    represent_nav_icon();

    /* UILayouts: follow placements from the real text metrics. */
    shape_idx[TA_FOLLOW_BASE] = TA_GLASS_IDX_BASE;
    shape_idx[TA_FOLLOW_ZONE] = TA_GLASS_IDX_ZONE;
    shape_idx[TA_FOLLOW_ARTIST] = TA_GLASS_IDX_ARTIST;
    shape_idx[TA_FOLLOW_ALBUM] = TA_GLASS_IDX_ALBUM;
    shape_idx[TA_FOLLOW_TITLE] = TA_GLASS_IDX_TITLE_VP;
    shape_idx[TA_FOLLOW_VOLUME] = TA_GLASS_IDX_VOLUME;
    shape_idx[TA_FOLLOW_TRANSPORT] = TA_GLASS_IDX_TRANSPORT;
    shape_idx[TA_FOLLOW_CLOCK] = TA_GLASS_IDX_CLOCK;
    shape_idx[TA_FOLLOW_NAV] = TA_GLASS_IDX_NAV;
    if (ta_follow_chrome_build(&g.chrome, shape_idx) != 0) {
        return -1;
    }
    memset(&m, 0, sizeof(m));
    m.panel_w = g.cfg.panel_w;
    m.panel_h = g.cfg.panel_h;
    m.text_x = g.cfg.text_x;
    m.text_y = g.cfg.text_y;
    m.text_h = g.cfg.text_h;
    m.gap = g.cfg.gap;
    m.button_y = g.cfg.button_y;
    m.transport_w = TA_CHROME_ICON_PX;
    m.transport_h = TA_CHROME_ICON_PX;
    m.nav_w = TA_CHROME_ICON_PX;
    m.nav_h = TA_CHROME_ICON_PX;
    if (ta_follow_chrome_place(&g.chrome, &m) != 0) {
        return -1;
    }

    /* Scene: one node per slot; clock is represent-time. */
    memset(&g.scene, 0, sizeof(g.scene));
    memset(g.nodes, 0, sizeof(g.nodes));
    for (i = 0; i < TA_FOLLOW_N; i++) {
        g.nodes[i].shape_idx = shape_idx[i];
        g.nodes[i].update_enum = TA_UPD_NOOP;
    }
    g.nodes[TA_FOLLOW_CLOCK].update_enum = TA_UPD_REPRESENT_TIME;
    g.scene.uilo = g.chrome.uilo;
    g.scene.accept_hit = g.chrome.accept_hit;
    g.scene.n_uilo = g.chrome.n;
    g.scene.nodes = g.nodes;
    g.scene.n_nodes = TA_FOLLOW_N;
    for (i = 0; i < 10; i++) {
        g.scene.digit_glyph[i] = g.cfg.glyphs->idx[(unsigned)('0' - 32) + i];
    }
    g.scene.colon_glyph = g.cfg.glyphs->idx[(unsigned)(':' - 32)];
    memcpy(g.scene.clock_hhmmss, g.ts[TS_CLOCK].text, 9);
    g.scene.clock_hhmmss[8] = '\0';

    mark_all_dirty();
    g.st.installs++;
    return 0;
}

/* ---- update / paint ---------------------------------------------------- */

static void backlight(int on) {
    if (g.lit == on) {
        return;
    }
    g.lit = on;
    if (g.be != NULL && g.be->set_backlight != NULL) {
        g.be->set_backlight(on);
    }
    if (on) {
        g.st.wakes++;
    } else {
        g.st.sleeps++;
    }
}

static void clock_string(char out[9]) {
    unsigned s;

    if (g.be != NULL && g.be->clock_hhmmss != NULL &&
        g.be->clock_hhmmss(out) == 0) {
        out[8] = '\0';
        return;
    }
    s = g.uptime_s;
    snprintf(out, 9, "%02u:%02u:%02u", (s / 3600u) % 100u, (s / 60u) % 60u,
             s % 60u);
}

int ta_glass_update(void) {
    char hhmmss[9];

    g.uptime_s++;
    if (g.lit) {
        g.idle_s++;
        if (g.idle_s >= TA_GLASS_SCREEN_OFF_S) {
            backlight(0);
        }
    }
    if (!g.installed) {
        return 0;
    }
    clock_string(hhmmss);
    if (strcmp(hhmmss, g.scene.clock_hhmmss) == 0 &&
        strcmp(hhmmss, g.ts[TS_CLOCK].text) == 0) {
        return 0; /* same second: nothing to represent */
    }
    memcpy(g.scene.clock_hhmmss, hhmmss, 9);
    memcpy(g.ts[TS_CLOCK].text, hhmmss, 9);
    /* Defs + dirty only; the clock L2R pack is rewritten, pixels untouched. */
    if (ta_draw_update(&g.scene) != 0) {
        g.st.errors++;
        return -1;
    }
    return 0;
}

unsigned ta_glass_page(void) {
    return g.swap.active;
}

int ta_glass_set_page(unsigned page) {
    if (!g.installed) {
        return -1;
    }
    if (page == g.swap.active) {
        return 0;
    }
    if (ta_shape_swap_set_active(&g.swap, page) != 0) {
        return -1;
    }
    mark_all_dirty();
    return 0;
}

void ta_glass_set_nav_down(int down) {
    int want = down ? 1 : 0;

    if (!g.installed || g.nav_down == want) {
        return;
    }
    g.nav_down = want;
    represent_nav_icon();
}

int ta_glass_nav_down(void) {
    return g.nav_down;
}

int ta_glass_add_page(unsigned shape_idx) {
    ta_shape_bitmap_t *ch;

    if (!g.installed || g.swap.n >= TA_SWAP_MAX) {
        return -1;
    }
    ch = ta_shape_table_get(shape_idx);
    if (ch == NULL || ch->pixels == NULL || ch->w != g.base.w ||
        ch->h != g.base.h) {
        return -1;
    }
    g.swap.child_idx[g.swap.n] = shape_idx;
    g.swap.n++;
    g.swap.dirty = 1;
    if (ta_shape_swap_bind(&g.swap) != 0) {
        g.swap.n--;
        return -1;
    }
    return (int)(g.swap.n - 1);
}

int ta_glass_paint(void) {
    ta_phase1_opts_t opts;
    ta_phase2_push_t pushes[TA_FOLLOW_N * 2];
    int n;
    int i;

    if (!g.installed) {
        return 0;
    }
    if (!g.lit) {
        return 0; /* dark glass: keep dirty for the wake paint */
    }
    /* Non-zero SwapShape page: one full-panel child, not follow chrome. */
    if (g.swap.active != 0) {
        const ta_shape_bitmap_t *hdr;

        if (ta_shape_swap_bind(&g.swap) != 0 || g.swap.pixels == NULL) {
            g.st.errors++;
            return -1;
        }
        hdr = ta_shape_table_get(ta_shape_swap_active_idx(&g.swap));
        if (hdr == NULL || hdr->pixels == NULL) {
            g.st.errors++;
            return -1;
        }
        g.be->push_rect(0, 0, (int)g.swap.w, (int)g.swap.h, hdr->pixels,
                        (int)hdr->w);
        g.swap.dirty = 0;
        g.st.pushes++;
        g.st.paints++;
        return 1;
    }
    memset(&opts, 0, sizeof(opts));
    opts.base_shape_idx = TA_GLASS_IDX_BASE;
    opts.base_x = ta_uilo_x(g.chrome.uilo[TA_FOLLOW_BASE]);
    opts.base_y = ta_uilo_y(g.chrome.uilo[TA_FOLLOW_BASE]);
    if (ta_draw_phase1(&g.scene, &opts) != 0) {
        g.st.errors++;
        return -1;
    }
    n = ta_draw_phase2(&g.scene, pushes, sizeof(pushes) / sizeof(pushes[0]));
    if (n < 0) {
        g.st.errors++;
        return -1;
    }
    /* phase2 lists nearest first; the glass wants farthest first so a
     * partially overlapping lower never overpaints a nearer rect. */
    for (i = n - 1; i >= 0; i--) {
        const ta_shape_bitmap_t *hdr = ta_shape_table_get(pushes[i].shape_idx);

        if (hdr == NULL || hdr->pixels == NULL) {
            continue;
        }
        g.be->push_rect(pushes[i].exterior.x, pushes[i].exterior.y,
                        pushes[i].exterior.w, pushes[i].exterior.h, hdr->pixels,
                        (int)hdr->w);
        g.st.pushes++;
    }
    g.st.paints++;
    return n;
}

int ta_glass_scroll_ox(int16_t ox) {
    if (!g.installed) {
        return 0;
    }
    if (g.ts[TS_TITLE].l2r.w <= g.title_vp.w) {
        return 0; /* fits: no scroll churn */
    }
    g.title_vp.ox = ox;
    g.title_vp.dirty = 1;
    mark_follow_dirty(TA_FOLLOW_TITLE);
    g.st.scrolls++;
    return 1;
}

int ta_glass_scroll_step(void) {
    int period;
    int ox;

    if (!g.installed || g.ts[TS_TITLE].l2r.w <= g.title_vp.w) {
        return 0;
    }
    period = (int)g.ts[TS_TITLE].l2r.w + TA_PHASE1_SCROLL_GAP;
    ox = (int)g.title_vp.ox + TA_GLASS_SCROLL_STEP;
    if (ox >= period) {
        ox -= period;
    }
    return ta_glass_scroll_ox((int16_t)ox);
}

/* ---- input ------------------------------------------------------------- */

void ta_glass_hit_boxes(uint16_t w[TA_FOLLOW_N], uint16_t h[TA_FOLLOW_N]) {
    size_t i;

    for (i = 0; i < TA_FOLLOW_N; i++) {
        const ta_shape_bitmap_t *hdr = NULL;

        if (i < g.chrome.n) {
            hdr = ta_shape_table_get(ta_uilo_shape(g.chrome.uilo[i]));
        }
        w[i] = hdr != NULL ? hdr->w : 0;
        h[i] = hdr != NULL ? hdr->h : 0;
        if (i == TA_FOLLOW_TRANSPORT || i == TA_FOLLOW_NAV) {
            w[i] = (uint16_t)(w[i] + 2u * g.cfg.hit_pad_x);
            h[i] = (uint16_t)(h[i] + 2u * g.cfg.hit_pad_y);
        }
    }
}

/* Any input is activity; a dark glass lights first. Returns 1 if it woke. */
static int activity(void) {
    g.idle_s = 0;
    if (!g.lit) {
        backlight(1);
        (void)ta_glass_paint();
        return 1;
    }
    return 0;
}

int ta_glass_touch(uint16_t x, uint16_t y, ta_session_id_t session) {
    uint16_t w[TA_FOLLOW_N];
    uint16_t h[TA_FOLLOW_N];
    int rc;

    if (activity()) {
        /* A dark tap lights the glass; it does not hit-test, so it cannot
         * toggle transport by accident. */
        return 1;
    }
    if (!g.installed) {
        g.st.misses++;
        return 1;
    }
    ta_glass_hit_boxes(w, h);
    rc = ta_react_touch(&g.chrome, x, y, session, w, h);
    if (rc == 0) {
        g.st.hits++;
    } else if (rc == 1) {
        g.st.misses++;
    } else {
        g.st.errors++;
    }
    return rc;
}

int ta_glass_rotate(int8_t steps, ta_session_id_t session) {
    (void)activity();
    if (steps == 0) {
        return 1;
    }
    if (ta_react_rotate(steps, session) != 0) {
        g.st.errors++;
        return -1;
    }
    g.st.hits++;
    return 0;
}
