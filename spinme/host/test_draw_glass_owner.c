/*
 * END test: Draw is the sole glass owner.
 *   ISR mail -> Draw queue -> hit walk -> ControlEvents -> MPD -> Net
 *   MPD status / Net text -> Draw defs -> update/phase1/phase2 -> pushes
 * Fake glass backend records exterior pushes and backlight; fake Net backend
 * defers completions so POLL_DONE can carry a status payload.
 */
#include "ta_controller.h"
#include "ta_draw_events.h"
#include "ta_draw_glass.h"
#include "ta_input_isr.h"
#include "ta_net_backend.h"
#include "ta_net_events.h"
#include "ta_registry.h"
#include "ta_router.h"
#include "ta_sched_events.h"

#include <stdio.h>
#include <stdlib.h>
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

/* ---- fake glass backend ------------------------------------------------ */

typedef struct rec {
    int x, y, w, h;
    const ta_pack66_t *px;
} rec_t;

static rec_t g_recs[64];
static int g_nrec;
static int g_backlight = 1;
static int g_backlight_calls;
static char g_clock[9] = "12:34:56";

static ta_pack66_t *fake_alloc(size_t count) {
    return (ta_pack66_t *)calloc(count, sizeof(ta_pack66_t));
}

static void fake_push(int x, int y, int w, int h, const ta_pack66_t *px,
                      int stride) {
    (void)stride;
    if (g_nrec < 64) {
        g_recs[g_nrec].x = x;
        g_recs[g_nrec].y = y;
        g_recs[g_nrec].w = w;
        g_recs[g_nrec].h = h;
        g_recs[g_nrec].px = px;
    }
    g_nrec++;
}

static void fake_backlight(int on) {
    g_backlight = on;
    g_backlight_calls++;
}

static int fake_clock(char out[9]) {
    memcpy(out, g_clock, 9);
    return 0;
}

static const ta_glass_backend_t k_be = {fake_alloc, fake_push, fake_backlight,
                                        fake_clock};

/* ---- fake Net backend (deferred) --------------------------------------- */

static int g_req_poll, g_req_toggle, g_req_volume, g_last_volume;

static int req_poll(void) {
    g_req_poll++;
    return 0;
}
static int req_toggle(void) {
    g_req_toggle++;
    return 0;
}
static int req_volume(int v) {
    g_req_volume++;
    g_last_volume = v;
    return 0;
}
static const ta_net_backend_t k_net = {req_poll, req_toggle, req_volume, NULL};

/* ---- glyph atlas: 3x5 block for every printable ascii ------------------ */

#define GW 3
#define GH 5
static ta_pack66_t g_ink[GW * GH];
static ta_pack66_t g_clear[GW * GH];
static ta_shape_bitmap_t g_glyphs[95];
static ta_glyph_map_t g_map;

static void build_atlas(void) {
    int i;
    for (i = 0; i < GW * GH; i++) {
        g_ink[i] = ta_pack66_rgba(0x3f, 0x3f, 0x3f, 3);
        g_clear[i] = ta_pack66_rgba(0, 0, 0, 0);
    }
    ta_glyph_map_clear(&g_map);
    for (i = 0; i < 95; i++) {
        char ch = (char)(32 + i);
        memset(&g_glyphs[i], 0, sizeof(g_glyphs[i]));
        g_glyphs[i].tag = TA_SHAPE_TAG_BITMAP;
        g_glyphs[i].w = GW;
        g_glyphs[i].h = GH;
        g_glyphs[i].pixels = ch == ' ' ? g_clear : g_ink;
        CHECK(ta_shape_table_set((unsigned)(1 + i), &g_glyphs[i]) == 0);
        CHECK(ta_glyph_map_set(&g_map, ch, (unsigned)(1 + i)) == 0);
    }
}

/* ---- helpers ----------------------------------------------------------- */

#define PANEL 64
static ta_pack66_t g_base[PANEL * PANEL];
static ta_event_envelope_t g_qstore[32];
static ta_queue_t g_q;
static ta_isr_mail_t g_mail;

static size_t pump(void) {
    ta_isr_mail_t *mails[1];
    mails[0] = &g_mail;
    return ta_draw_pump(mails, 1);
}

static int post_type(const char *to, ta_event_type_t type) {
    ta_event_envelope_t env;
    ta_env_clear(&env);
    env.event.type = type;
    env.session_id = 7;
    (void)ta_env_set_src(&env, "Test");
    return ta_registry_post(to, &env);
}

static int post_set_route(const char *target) {
    ta_event_envelope_t env;
    ta_env_clear(&env);
    env.event.type = TA_EV_SET_ROUTE;
    env.session_id = 7;
    (void)ta_env_set_src(&env, "Test");
    (void)ta_event_set_ctrl_set_route(&env.event, target);
    return ta_registry_post(TA_CONTROLLER_NAME, &env);
}

static int post_draw_update(uint8_t kind) {
    ta_event_envelope_t env;
    ta_env_clear(&env);
    env.event.type = TA_EV_DRAW_UPDATE;
    env.session_id = 7;
    (void)ta_env_set_src(&env, "Test");
    env.event.u.draw_update.kind = kind;
    return ta_registry_post(TA_DRAW_NAME, &env);
}

static int post_scroll_ox(int16_t ox, int has_ox) {
    ta_event_envelope_t env;
    ta_env_clear(&env);
    env.event.type = TA_EV_DRAW_SCROLL_OX;
    env.session_id = 7;
    (void)ta_env_set_src(&env, "Test");
    env.event.u.draw_scroll_ox.ox = ox;
    env.event.u.draw_scroll_ox.has_ox = (uint8_t)(has_ox ? 1 : 0);
    return ta_registry_post(TA_DRAW_NAME, &env);
}

int main(void) {
    ta_glass_cfg_t cfg;
    const ta_follow_chrome_t *chrome;
    int i;
    int before;

    ta_registry_reset();
    ta_shape_table_reset();
    ta_draw_reset();
    ta_router_reset();
    ta_mpd_reset();
    ta_net_reset();
    ta_sched_reset();
    build_atlas();
    for (i = 0; i < PANEL * PANEL; i++) {
        g_base[i] = ta_pack66_rgba(10, 10, 10, 3);
    }

    ta_draw_start();
    ta_router_start();
    ta_mpd_start();
    ta_net_start();
    ta_sched_start();
    ta_net_set_backend(&k_net);
    CHECK(ta_queue_init(&g_q, g_qstore, 32) == 0);
    ta_draw_bind_queue(&g_q);
    ta_isr_mail_reset(&g_mail);

    memset(&cfg, 0, sizeof(cfg));
    cfg.panel_w = PANEL;
    cfg.panel_h = PANEL;
    cfg.base_pixels = g_base;
    cfg.glyphs = &g_map;
    cfg.text_h = GH;
    cfg.view_w = 30;
    cfg.hit_pad_x = 4;
    cfg.hit_pad_y = 2;
    cfg.text_x = 2;
    cfg.text_y = 10;
    cfg.gap = 1;
    cfg.button_y = 1;
    ta_glass_set_backend(&k_be);
    ta_glass_set_cfg(&cfg);

    /* 1. Activate MPD: SET_SHAPE_STACK waits in Draw's queue until pumped. */
    CHECK(post_set_route(TA_MPD_NAME) == 0);
    CHECK(post_type(TA_CONTROLLER_NAME, TA_EV_CTRL_SET_ACTIVE) == 0);
    CHECK(!ta_glass_installed());
    CHECK(pump() >= 1);
    CHECK(ta_glass_installed());
    CHECK(ta_glass_page() == 0);
    CHECK(ta_glass_set_page(0) == 0);
    CHECK(ta_glass_set_page(1) == -1); /* n=1 until add_page */
    CHECK(ta_draw_stats()->set_stack == 1);
    /* First paint: every slot pushed, base first (farthest-first order). */
    CHECK(g_nrec == TA_FOLLOW_N);
    CHECK(g_recs[0].w == PANEL && g_recs[0].h == PANEL);
    CHECK(g_recs[0].px == g_base);
    CHECK(strcmp(ta_glass_text(TA_DRAW_TEXT_ZONE), "spinme") == 0);
    chrome = ta_glass_chrome();
    CHECK(ta_uilo_x(chrome->uilo[TA_FOLLOW_ZONE]) == 2);
    CHECK(ta_uilo_y(chrome->uilo[TA_FOLLOW_ZONE]) == 10);
    CHECK(ta_uilo_y(chrome->uilo[TA_FOLLOW_ARTIST]) == 10 + GH + 1);
    CHECK(ta_uilo_y(chrome->uilo[TA_FOLLOW_TRANSPORT]) == 1);

    /* 2. Clean glass: PAINT pushes nothing. */
    before = g_nrec;
    CHECK(post_type(TA_DRAW_NAME, TA_EV_DRAW_PAINT) == 0);
    CHECK(pump() == 1);
    CHECK(g_nrec == before);

    /* 3. ISR touch on transport -> CTRL_TOGGLE -> MPD -> Net toggle. */
    {
        uint16_t tx = (uint16_t)(ta_uilo_x(chrome->uilo[TA_FOLLOW_TRANSPORT]) + 1);
        uint16_t ty = (uint16_t)(ta_uilo_y(chrome->uilo[TA_FOLLOW_TRANSPORT]) + 1);
        CHECK(ta_isr_post_touch(&g_mail, tx, ty) == 0);
    }
    CHECK(pump() >= 1);
    CHECK(ta_mpd_stats()->toggle == 1);
    CHECK(g_req_toggle == 1);
    CHECK(ta_glass_stats()->hits == 1);
    /* Miss on the base: no ControlEvent. */
    CHECK(ta_isr_post_touch(&g_mail, 0, PANEL - 1) == 0);
    CHECK(pump() >= 1);
    CHECK(ta_mpd_stats()->toggle == 1);
    CHECK(ta_glass_stats()->misses == 1);

    /* 4. ISR rotary +3 -> CTRL_VOLUME -> desired leads the glass. */
    before = g_nrec;
    CHECK(ta_isr_post_rotary(&g_mail, 3, 0) == 0);
    CHECK(pump() >= 1);
    CHECK(ta_mpd_volume() == TA_MPD_VOL_DEFAULT + 3);
    CHECK(ta_mpd_stats()->coalesced == 1); /* toggle SET still in flight */
    CHECK(ta_glass_desired() == TA_MPD_VOL_DEFAULT + 3);
    CHECK(g_nrec == before + 1); /* only the volume exterior */
    CHECK(g_recs[before].y == ta_uilo_y(chrome->uilo[TA_FOLLOW_VOLUME]));
    CHECK(ta_draw_stats()->isr_drained == 3);

    /* 5. Net completes: SET_DONE flushes the coalesced volume, then settles
     * into a POLL whose DONE carries player status -> chrome follows. */
    ta_net_backend_complete_ex(3, NULL, 0); /* toggle done */
    CHECK(g_req_volume == 1 && g_last_volume == TA_MPD_VOL_DEFAULT + 3);
    ta_net_backend_complete_ex(3, NULL, 0); /* volume done -> poll */
    CHECK(g_req_poll == 1);
    {
        uint8_t status[TA_NET_STATUS_LEN];
        status[TA_NET_STATUS_VOLUME] = 40;
        status[TA_NET_STATUS_PLAYING] = 1;
        ta_net_backend_complete_ex(1, status, sizeof(status));
    }
    CHECK(pump() >= 1);
    CHECK(ta_mpd_polled() == 40);
    CHECK(ta_mpd_volume() == 40); /* nothing pending: follow the player */
    CHECK(ta_glass_polled() == 40);
    CHECK(ta_glass_playing() == 1);

    /* 6. Net text -> Draw SET_TEXT chunks; long title scrolls in viewport. */
    before = g_nrec;
    CHECK(ta_draw_post_text(TA_DRAW_TEXT_TITLE,
                            "a very long title that needs to scroll", 7,
                            "Net") == 0);
    CHECK(pump() >= 2);
    CHECK(strcmp(ta_glass_text(TA_DRAW_TEXT_TITLE),
                 "a very long title that needs to scroll") == 0);
    CHECK(g_nrec == before + 1);
    CHECK(g_recs[before].w == 30); /* viewport window, not content width */
    before = g_nrec;
    CHECK(post_scroll_ox(5, 1) == 0);
    CHECK(pump() == 1);
    CHECK(g_nrec == before + 1);
    CHECK(ta_glass_stats()->scrolls == 1);
    /* Cadence tick without ox: Draw steps ox itself and repaints. */
    before = g_nrec;
    CHECK(post_scroll_ox(0, 0) == 0);
    CHECK(pump() == 1);
    CHECK(g_nrec == before + 1);
    CHECK(ta_glass_stats()->scrolls == 2);
    CHECK(g_recs[before].w == 30);
    /* Short artist fits: scroll is a no-op for it, text clipped to view. */
    CHECK(ta_draw_post_text(TA_DRAW_TEXT_ARTIST, "abc", 7, "Net") == 0);
    CHECK(pump() == 1);
    CHECK(strcmp(ta_glass_text(TA_DRAW_TEXT_ARTIST), "abc") == 0);

    /* 7. Cadence update: clock represent-time dirties only the clock. */
    before = g_nrec;
    CHECK(post_draw_update(TA_DRAW_UPD_CADENCE) == 0);
    CHECK(pump() == 1);
    CHECK(g_nrec == before + 1);
    CHECK(g_recs[before].y == ta_uilo_y(chrome->uilo[TA_FOLLOW_CLOCK]));
    before = g_nrec;
    CHECK(post_draw_update(TA_DRAW_UPD_CADENCE) == 0);
    CHECK(pump() == 1);
    CHECK(g_nrec == before); /* same second: nothing */

    /* 8. Idle -> backlight off; dark glass keeps dirty; dark tap only wakes. */
    for (i = 0; i < TA_GLASS_SCREEN_OFF_S; i++) {
        CHECK(post_draw_update(TA_DRAW_UPD_CADENCE) == 0);
    }
    CHECK(pump() == (size_t)TA_GLASS_SCREEN_OFF_S);
    CHECK(g_backlight == 0);
    CHECK(ta_glass_backlight() == 0);
    before = g_nrec;
    CHECK(post_draw_update(TA_DRAW_UPD_BASE_DIRTY) == 0);
    CHECK(pump() == 1);
    CHECK(g_nrec == before); /* dark: nothing pushed */
    {
        uint16_t tx = (uint16_t)(ta_uilo_x(chrome->uilo[TA_FOLLOW_TRANSPORT]) + 1);
        uint16_t ty = (uint16_t)(ta_uilo_y(chrome->uilo[TA_FOLLOW_TRANSPORT]) + 1);
        CHECK(ta_isr_post_touch(&g_mail, tx, ty) == 0);
    }
    CHECK(pump() >= 1);
    CHECK(g_backlight == 1);
    CHECK(ta_mpd_stats()->toggle == 1); /* dark tap did not hit-test */
    CHECK(g_nrec == before + TA_FOLLOW_N); /* base dirtied all: full repaint */
    CHECK(g_recs[before].px == g_base);

    /* 9. Base dirty while lit: everything above repaints after the base. */
    before = g_nrec;
    CHECK(post_draw_update(TA_DRAW_UPD_BASE_DIRTY) == 0);
    CHECK(pump() == 1);
    CHECK(g_nrec == before + TA_FOLLOW_N);

    /* Text pixels: the title window carries base under the glyph paper. */
    {
        const ta_shape_bitmap_t *vp = ta_shape_table_get(TA_GLASS_IDX_TITLE_VP);
        uint8_t r, gg, b, a;
        CHECK(vp != NULL && vp->pixels != NULL);
        if (vp != NULL && vp->pixels != NULL) {
            ta_unpack66(vp->pixels[0], &r, &gg, &b, &a);
            CHECK(a == 3); /* never transparent on the glass */
        }
    }

    /* 10. SwapShape page: add a second full-panel child and switch to it. */
    {
        static ta_pack66_t page1_px[PANEL * PANEL];
        static ta_shape_bitmap_t page1;
        memset(page1_px, 0, sizeof(page1_px));
        page1_px[0] = ta_pack66_rgba(4, 5, 6, 3);
        memset(&page1, 0, sizeof(page1));
        page1.tag = TA_SHAPE_TAG_BITMAP;
        page1.w = PANEL;
        page1.h = PANEL;
        page1.pixels = page1_px;
        CHECK(ta_shape_table_set(920, &page1) == 0);
        CHECK(ta_glass_add_page(920) == 1);
        before = g_nrec;
        CHECK(ta_glass_set_page(1) == 0);
        CHECK(ta_glass_page() == 1);
        CHECK(post_type(TA_DRAW_NAME, TA_EV_DRAW_PAINT) == 0);
        CHECK(pump() == 1);
        CHECK(g_nrec == before + 1);
        CHECK(g_recs[before].px == page1_px);
        CHECK(ta_glass_set_page(0) == 0);
        CHECK(ta_glass_page() == 0);
    }

    CHECK(ta_draw_stats()->unknown == 0);
    CHECK(ta_glass_stats()->errors == 0);
    ta_queue_fini(&g_q);

    if (failures != 0) {
        fprintf(stderr, "test_draw_glass_owner: %d/%d checks failed\n",
                failures, checks);
        return 1;
    }
    printf("test_draw_glass_owner: %d checks ok\n", checks);
    return 0;
}
