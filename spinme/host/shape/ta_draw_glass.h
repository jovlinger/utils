/*
 * Draw glass model: the follow chrome as UILayout + Shapes, owned by the
 * Draw TaskActor alone. Nothing else touches the panel.
 *
 * Glue (device or host test) provides a backend seam (pixel alloc, exterior
 * push, backlight, wall clock) and a config (panel size, base pixels, glyph
 * map). Draw builds the chrome on DRAW_SET_SHAPE_STACK, keeps text / status
 * state, runs update -> phase1 -> phase2 and pushes whole exteriors
 * farthest-first. No panel-sized glass shadow: per-shape local pixmaps with
 * the base crop composited under each text line (PLAN Q1).
 */
#ifndef SPINME_TA_DRAW_GLASS_H
#define SPINME_TA_DRAW_GLASS_H

#include "ta_draw_phase2.h"
#include "ta_event.h"
#include "ta_follow_chrome.h"
#include "ta_text.h"
#include "ta_uilayout.h"

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Chrome shape idxs live high (PLAN: rare items in the 900s). */
enum {
    TA_GLASS_IDX_BASE = 900,
    TA_GLASS_IDX_ZONE = 901,
    TA_GLASS_IDX_ARTIST = 902,
    TA_GLASS_IDX_ALBUM = 903,
    TA_GLASS_IDX_TITLE_VP = 904,  /* Viewport over TITLE_L2R */
    TA_GLASS_IDX_TITLE_L2R = 905, /* not a UILayout; viewport child */
    TA_GLASS_IDX_VOLUME = 906,
    TA_GLASS_IDX_TRANSPORT = 907, /* centered play/pause outline icon */
    TA_GLASS_IDX_CLOCK = 908,
    TA_GLASS_IDX_SWAP = 909, /* SwapShape root; child 0 = follow page */
    TA_GLASS_IDX_NAV = 910,  /* 12 oclock up/down solid arrow */
    TA_GLASS_IDX_DEBUG = 911 /* 6 oclock debug control */
};

#define TA_GLASS_TEXT_MAX 96
#define TA_GLASS_LINE_W_MAX 1024 /* scrolling title content cap */
#define TA_GLASS_PACK_WORDS 48
#ifndef TA_GLASS_SCREEN_OFF_S
#define TA_GLASS_SCREEN_OFF_S 30 /* idle cadence ticks before backlight off */
#endif
#define TA_GLASS_UNKNOWN 0xFFu

/* Text fields a producer may set (DRAW_SET_TEXT payload[0]). */
enum {
    TA_DRAW_TEXT_ZONE = 0,
    TA_DRAW_TEXT_ARTIST = 1,
    TA_DRAW_TEXT_ALBUM = 2,
    TA_DRAW_TEXT_TITLE = 3,
    TA_DRAW_TEXT_N = 4
};

typedef struct ta_glass_backend {
    /* Required once a stack is installed. Device: PSRAM. */
    ta_pack66_t *(*alloc_px)(size_t count);
    /* Push one whole exterior of pack66 (stride in px). Required. */
    void (*push_rect)(int x, int y, int w, int h, const ta_pack66_t *px,
                      int stride_px);
    /* Optional. */
    void (*set_backlight)(int on);
    /* Optional: "HH:MM:SS" into out (9 bytes). Return 0 on success. */
    int (*clock_hhmmss)(char out[9]);
} ta_glass_backend_t;

typedef struct ta_glass_cfg {
    uint16_t panel_w;
    uint16_t panel_h;
    ta_pack66_t *base_pixels;     /* panel_w*panel_h pack66, glue-owned */
    const ta_glyph_map_t *glyphs; /* ascii -> glyph ShapeBitMap idx (<128) */
    const int8_t *kern_table;     /* optional, indexed by ascii-32 */
    uint16_t text_h;              /* line height = max glyph h */
    uint16_t view_w;              /* text line window width */
    uint16_t hit_pad_x;           /* transport fat hit box pads */
    uint16_t hit_pad_y;
    int text_x;
    int text_y;
    int gap;
    int button_y;
} ta_glass_cfg_t;

typedef struct ta_glass_stats {
    unsigned installs;
    unsigned paints;
    unsigned pushes;
    unsigned text_sets;
    unsigned status_sets;
    unsigned wakes;
    unsigned sleeps;
    unsigned hits;
    unsigned misses;
    unsigned scrolls;
    unsigned errors;
} ta_glass_stats_t;

void ta_glass_reset(void);
void ta_glass_set_backend(const ta_glass_backend_t *b);
void ta_glass_set_cfg(const ta_glass_cfg_t *c);
const ta_glass_stats_t *ta_glass_stats(void);

/* Build chrome shapes + UILayouts; everything dirty. -1 if unconfigured. */
int ta_glass_install_stack(void);
int ta_glass_installed(void);

/* Text / status mutate definitions and dirty; they do not paint. */
int ta_glass_set_text(uint8_t field, const char *ascii);
/* 0xFF = leave unchanged. playing / playing_polled: 0/1.
 * Desired transport glyph leads; low a2 until playing_polled agrees. */
void ta_glass_set_status(uint8_t polled, uint8_t desired, uint8_t playing,
                         uint8_t playing_polled);
void ta_glass_base_dirty(void);
int ta_glass_scroll_ox(int16_t ox);
/* Scheduler tick without payload: advance the title by TA_GLASS_SCROLL_STEP
 * px, wrapping at content width + gap. Returns 1 when something moved. */
int ta_glass_scroll_step(void);
#ifndef TA_GLASS_SCROLL_STEP
#define TA_GLASS_SCROLL_STEP 2
#endif

/* Cadence update (clock represent-time + idle/backlight). */
int ta_glass_update(void);
/* phase1 + phase2 + farthest-first pushes. Returns pushes or -1. */
int ta_glass_paint(void);

/* Input from ISR mail. Touch returns hit role posted (see ta_hit_dispatch),
 * 1 = miss / dark wake only, -1 = error. Rotate always posts CTRL_VOLUME. */
int ta_glass_touch(uint16_t x, uint16_t y, ta_session_id_t session);
int ta_glass_rotate(int8_t steps, ta_session_id_t session);

/* Queries (tests, device "query" line). */
int ta_glass_backlight(void);
const char *ta_glass_text(uint8_t field);
int ta_glass_polled(void);
int ta_glass_desired(void);
int ta_glass_playing(void);
const ta_follow_chrome_t *ta_glass_chrome(void);
/* Panel base pack66 framebuffer (glue-owned); NULL if unset. */
const ta_pack66_t *ta_glass_base_pixels(void);
void ta_glass_panel_size(uint16_t *out_w, uint16_t *out_h);
/* SwapShape page: 0 = follow chrome; later pages are full-panel children. */
unsigned ta_glass_page(void);
int ta_glass_set_page(unsigned page);
/* Append a same-size panel child (KV editor, etc.). Returns new page or -1. */
int ta_glass_add_page(unsigned shape_idx);
/* 12 oclock arrow: 0 = up/back, 1 = down/select (selecting mode). */
void ta_glass_set_nav_down(int down);
int ta_glass_nav_down(void);
int ta_glass_selecting(void);
/* Hit boxes used by the walk (transport padded). */
void ta_glass_hit_boxes(uint16_t w[TA_FOLLOW_N], uint16_t h[TA_FOLLOW_N]);

#ifdef __cplusplus
}
#endif
#endif
