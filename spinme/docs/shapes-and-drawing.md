# Shapes and drawing

Shape table: `TA_SHAPE_MAX` 1024. UILayout points at a shape idx; only
UILayouts (plus chrome stack-compose) paint to glass. Draw is the sole glass
owner (`ta_draw_glass` / `ta_glass_paint`); see TaskActors for Draw events.

## Glass path without flicker

Goal: alpha-composited bits reach the ST77916 without tearing, full-frame
flashes, or "base wiped then chrome pops in" frames.

**No full-frame SRAM double buffer.** A 360x360 RGB565 pair is ~518 KB and
was rejected. The panel path is **partial updates** through a small **QSPI
DMA staging band** in internal/`MALLOC_CAP_DMA` SRAM. PSRAM holds shape
pixmaps; peripherals cannot DMA from PSRAM, so every push copies through
that band.

**Only XY reaches the glass.** Product paint bakes shapes in CPU memory,
then loads each exterior into a scratch `TA_SD_TAG_XY` with per-row RLC
dirty spans (`ta_sd_xy_blit_glass` / `ta_sd_xy_push_dirty`). The wire sees
row spans, not a random full rewrite of unchanged glass.

**Pipeline (`ta_glass_paint`), ordered so the user never sees a half frame:**

1. **`ta_draw_update`** -- set dirty flags / defs only. Never rewrites
   `*pixels`. Clock digit packs may change here without touching glass.
2. **`ta_draw_phase1`** -- farthest -> nearest, rebuild dirty **local**
   pixmaps only. Text paper is transparent: each dirty L2R/Viewport
   composites the matching crop of the base (artwork) under glyphs
   (`base_shape_idx`). There is no panel-sized shadow bitmap. Viewports
   blit at `-ox` and again at `period - ox` for wrap.
3. **`ta_draw_phase2`** -- nearest -> farthest coverage cull; emit the
   exterior push list; clear dirty bits.
4. **Execute pushes farthest-first** so a farther rect never overwrites a
   nearer one already on glass.
5. **TRANSPORT / NAV** never push a base-only wipe. `ta_stack_compose`
   builds one scratch: base crop + follow text under the icon + icon with
   pack66 `over`, then one XY/RLC push of that exterior.

**Alpha:** pack66 `A2` -- 0 skip, 1..2 blend, 3 opaque. `over` runs in the
local pixmap or compose scratch **before** the band sees bytes, so the
panel gets already-resolved RGB (device path still pack66 until the
driver expands). Pending vs settled chrome uses a2=1 vs a2=2 so track text
shows through strokes without a second full-panel pass.

**Dirty policy:** a dirty base dirties everything above it (z+). Unchanged
cadence updates that do not mark dirty do not push. Idle backlight-off
skips paints entirely; wake marks all dirty once and repaints.

**Locking:** do not hold the shape lock across a stalling QSPI TX; snapshot
into the SRAM band (or finish the span) then release. ISR never paints.

**Host checks:** `test_draw_glass_contract`, `test_draw_glass_owner`,
`test_under_image`, `test_xy_timed_redraw` (bit-identical RLC path),
`test_screenshots` (pixel RGB goldens).

### Tags (as-built)

| Tag | Value | Struct | Role |
|-----|-------|--------|------|
| `TA_SHAPE_TAG_BITMAP` | 1 | `ta_shape_bitmap_t` | Fixed pack66 pixmap (`w`,`h`,`*pixels`) |
| `TA_SHAPE_TAG_L2R` | 2 | `ta_shape_l2r_t` | Left-to-right composite of child bitmaps via shapepack |
| `TA_SHAPE_TAG_VIEWPORT` | 3 | `ta_shape_viewport_t` | Window over a child; `ox`/`oy` scroll |
| `TA_SHAPE_TAG_SWAP` | 4 | `ta_shape_swap_t` | N same-size children; show exactly one `active` |

Under-image / album art is a **BitMap** used as the panel base, not a fifth
tag.

### pack66 pixel word

```text
bits  0..5   R6
bits  8..13  G6
bits 16..21  B6
bits 24..25  A2   (0 with RGB=0 = hole, 1..2 blend, 3 opaque)
```

Hole constant: `TA_PACK66_TRANSPARENT` (`0`). Nonzero RGB with a2==0 is
**clamped additive**, not a hole -- glyph clear texels must use the constant.

Pseudo:

```
pack66(r,g,b,a) = (r&63) | (g&63)<<8 | (b&63)<<16 | (a&3)<<24
over(dst, src):
  if src == TA_PACK66_TRANSPARENT: return dst
  if src.a == 0: return additive(dst, src)   # not a hole
  if src.a >= 3: return src
  return pack66( (src.rgb*src.a + dst.rgb*(3-src.a))/3 , a=3 )
```

### UILayout word (display list entry, not a Shape)

One `uint32_t`:

```text
bit 0        dirty
bit 1        pad
bits 2..11   x   (int10, 0..1023)
bits 12..21  y   (int10)
bits 22..31  shape idx (idx10, 0..1023)
```

`accept_hit[]` is a parallel `uint8_t` array (not packed into the word).

### Shapepack index packing (ShapeL2R `pack[]`)

Each pack word is a `uint32_t`. The **top 2 bits are the density tag**; the
**remaining 30 bits** hold tightly packed child shape idxs (low bits first).
Idx `0` is the stream terminator (`TA_SHAPEPACK_END`).

| Tag enum | Top2 | Name | Idx width | Max idxs / word | Idx bits used |
|----------|------|------|-----------|-----------------|---------------|
| `TA_PACK_TAG_6x5` | `00` | six x 5-bit | 5 | 6 | 30 (bits 0..29) |
| `TA_PACK_TAG_5x6` | `01` | five x 6-bit | 6 | 5 | 30 |
| `TA_PACK_TAG_4x7` | `10` | four x 7-bit | 7 | 4 | 28 (bits 0..27) |
| `TA_PACK_TAG_3x10` | `11` | three x 10-bit | 10 | 3 | 30 |

**6x5 explicit layout** (densest; glyph runs often use this when idxs < 32):

```text
uint32_t word:
  bits 31..30  tag = 00  (TA_PACK_TAG_6x5)
  bits 29..25  idx5   (6th child, slot 5)
  bits 24..20  idx4
  bits 19..15  idx3
  bits 14..10  idx2
  bits  9..5   idx1
  bits  4..0   idx0   (1st child, slot 0)
```

Encode pseudo:

```
encode(idxs[0..n), tag):
  bpi = {6x5:5, 5x6:6, 4x7:7, 3x10:10}[tag]
  ipw = {6x5:6, 5x6:5, 4x7:4, 3x10:3}[tag]
  while idxs remain:
    word = (tag & 3) << 30
    for slot in 0 .. ipw-1 while idxs remain:
      word |= (idx & ((1<<bpi)-1)) << (slot * bpi)
    emit word
  emit terminator: (tag & 3) << 30   # all idx fields zero
```

Decode one word: read tag from bits 31..30, peel `ipw` fields; if every
idx is 0, the word is end-of-stream.

### Pseudo: each shape kind

**BitMap**

```
bake(bitmap):  # already has pixels; phase1 no-op
paint(dst, ox, oy, bitmap):
  for each pixel p in bitmap:
    if p.a != 0: dst[ox+x,oy+y] = over(dst[...], p)
```

**ShapeL2R**

```
bake(l2r):
  clear l2r.pixels
  x = 0
  for idx in unpack(l2r.pack):           # stop at idx 0
    child = shape_table[idx]             # BitMap glyph etc.
    blit child at (x, 0) into l2r.pixels
    x += child.w + kerning_for_item
  l2r.w, l2r.h = computed size
```

**Viewport**

```
bake(vp):
  clear vp.pixels
  blit_base_crop into vp.pixels at window (ex,ey)   # optional under
  child = shape_table[vp.child_idx]
  blit child at (-vp.ox, -vp.oy) into vp.pixels
  if child.w > vp.w: also blit wrapped copy at period - ox
```

**SwapShape**

```
bind(swap):
  require all children same w/h and non-null pixels
  swap.pixels = alias of children[swap.active].pixels
set_active(i):
  swap.active = i; dirty; bind again
paint: same as BitMap using aliased pixels
```

### Chrome icon bitmaps (play / pause / arrows)

These are ordinary **BitMap** shapes filled by `ta_chrome_icons_*`, then
shown through follow slots TRANSPORT and NAV.

| Glyph | API | Size | Geometry | a2 |
|-------|-----|------|----------|-----|
| Play | `ta_chrome_icon_play_outline` | 90x90 | Three thick strokes: left vertical + two diagonals to a tip (hollow triangle outline) | body_a2 from caller |
| Pause (stop bars) | `ta_chrome_icon_pause_outline` | 90x90 | Two vertical rounded bars (outline strokes) | body_a2 from caller |
| Up arrow | `ta_chrome_icon_up_solid` | 60x60 | Filled triangle head + stem | always opaque a2=3 |
| Down arrow | `ta_chrome_icon_down_solid` | 60x60 | Filled triangle head + stem | always opaque a2=3 |

**Play / pause (center transport)**

- Placement: panel center (`(panel - 90)/2`).
- Meaning: tap toggles play/pause (`TA_FN_TRANSPORT_TOGGLE`).
- Desired glyph leads; ink a2 tracks poll agreement:
  - `a2=1` (`TA_CHROME_A2_PENDING`) while `playing != playing_polled`
  - `a2=2` (`TA_CHROME_A2_SETTLED`) when they agree (still translucent so
    track text shows through the strokes)
- Paint path: `ta_stack_compose_exterior` = base crop + follow text layers
  under TRANSPORT + icon, then one resolved push (never base-only wipe).

Play outline pseudo:

```
play_outline(px, w, body_a2):
  clear px to a=0
  left, right, top, bot, mid = margins of w
  stroke_seg(left,top -> left,bot, thickness w/10)
  stroke_seg(left,top -> right,mid, ...)
  stroke_seg(left,bot -> right,mid, ...)
```

Pause outline pseudo:

```
pause_outline(px, w, body_a2):
  clear px
  place two bar rects left/right of center
  stroke each bar's four edges (capsule look)
```

**Up / down (12 o'clock nav)**

- Placement: top center (`button_y`), **above** the SwapShape page content.
- Same hit box; glyph flips with mode:
  - **Selected**: solid **up** = enter choosing / back-out affordance
  - **Selecting**: solid **down** = commit the previewed Swap child
- Wired as `TA_FN_NAV` (not owned by SwapShape itself).

Up solid pseudo:

```
up_solid(px, w):
  clear; a2 = opaque
  fill_tri_aa(apex at top, base at mid)
  stroke_seg stem mid -> bottom
```

### Follow chrome slots

| Slot | Index | Hit? | Dynamic high-z? | Shape role |
|------|-------|------|-----------------|------------|
| BASE | 0 | no | no (paint-once) | BitMap album / disintegration |
| ZONE | 1 | no | no | L2R text |
| ARTIST | 2 | no | no | L2R text |
| ALBUM | 3 | no | no | L2R text |
| TITLE | 4 | no | yes (scroll) | Viewport over TITLE L2R; y centered on transport |
| VOLUME | 5 | yes | no | L2R text |
| TRANSPORT | 6 | yes | no | BitMap play/pause 90px |
| CLOCK | 7 | no | yes | L2R text |
| NAV | 8 | yes | no | BitMap up/down 60px |

Built by `ta_follow_chrome_build` / `ta_follow_chrome_place`.

### SwapShape modes

| Mode | Meaning |
|------|---------|
| Selected | Committed child (e.g. MPD follow page). No chooser ring. |
| Selecting | Overlay on; rotary steps `active`; down-arrow commits. |

Shapes do not hold function pointers. Interactive slots carry `fn_enum`;
`ta_wire_touch` / `ta_wire_rotary` switch on it.

### XYShape-only glass write (`ta_shape_draw`)

Only `TA_SD_TAG_XY` reaches the glass. Each XY owns a pixmap plus per-row RLC
dirty (`n=2` words, `/2` units). Rebuild from child -> mark-full or derive RLC
-> `ta_sd_xy_blit_glass` / `ta_sd_xy_push_dirty`. Host `test_xy_timed_redraw`
paints 0-9 / a-j solely through that path. Product `ta_glass_paint` bakes via
phase1/phase2, then loads each exterior into a scratch XY and pushes RLC spans.

### Pseudo: whole UI paint (follow page)

```
glass_paint():
  if swap.active != 0:
    glass_push_xy(full panel of active swap child); return

  phase1(scene):                     # bake dirty L2R / Viewport / Swap bind
  pushes = phase2(scene)             # nearest-first dirty exteriors
  for push in reverse(pushes):       # farthest first on glass
    hdr = shape_table[push.shape]
    if hdr is TRANSPORT or NAV:
      composed = stack_compose(
        base_crop(exterior),
        blit each follow slot 1 .. top_slot-1,   # zone..volume under transport
        blit hdr icon at (0,0) with a2)
      glass_push_xy(exterior, composed)   # scratch XY + RLC spans
    else:
      glass_push_xy(exterior, hdr.pixels)

stack_compose(dst, ex, ey, ...):
  blit base into dst
  for slot in ZONE .. (top_slot-1):
    blit shape_table[uilo[slot]] at (uilo.x-ex, uilo.y-ey)
  blit top icon with pack66 over
```

### Pixel-perfect PNG UI tests

`spinme/host/test_screenshots` loads device `glyphs.bin` +
`disintegration_360.rgba`, paints the 360 glass into
`build/ui_actual/`, and compares decoded RGB to goldens under
`spinme/screenshots/` (`main_mpd`, `main_playing`, `selecting_overlay`,
`kv_view`, `kv_edit`). Refresh: `SPINME_UI_UPDATE_GOLDEN=1`.

### Host unit tests (docstrings)

Live under `spinme/host/tests/local/test_*.c`. Run via `make test` (or one binary
under `build/`). Each file's leading comment is the contract a fresh agent
should read first:

| File | Docstring |
|------|-----------|
| `test_actor.c` | Registers an actor on init and removes it on exit. |
| `test_all_init.c` | Broadcast perform_init delivers once to every registered actor. |
| `test_artwork.c` | Artwork pipeline: calm Q8 upscale to pack66, skip default art, oneshot album change. |
| `test_boot.c` | Boot walks KV roster, stub-loads each actor blob, calls init. |
| `test_controller.c` | Controller routes SetActive/ControlEvents to MPD or Sonos stubs. |
| `test_draw_events.c` | Draw event switch handles ops and async reply_to completions. |
| `test_draw_glass_contract.c` | Glass pipeline contract: update + phase1 + phase2 + under-image together. |
| `test_draw_glass_owner.c` | End-to-end: Draw owns glass -- ISR hit, MPD/Net status, paint pushes. |
| `test_draw_phase1.c` | phase1 bakes dirty L2R/viewport farthest-to-nearest (no LCD push). |
| `test_draw_phase2.c` | phase2 emits whole dirty exteriors, culls covered ones, clears dirty. |
| `test_draw_update.c` | update marks defs/dirty and shadow-propagates without rewriting pixels. |
| `test_event_envelope.c` | Envelope fields + typed event union round-trip (no sync RPC). |
| `test_follow_chrome.c` | Follow chrome: nine UILayout slots, paint-once vs high-z title/clock. |
| `test_hit_dispatch.c` | Hit walk on accept_hit slots posts ControlEvents through Router. |
| `test_input_isr.c` | Encoder gray/velocity decode; touch/rotary post into Draw ISR mail. |
| `test_isr_mail.c` | ISR mail ring accepts FromISR posts and drains into the Draw queue. |
| `test_kv.c` | NVM KV put/get copy-out and current_controller config key. |
| `test_kv_actor.c` | KV actor set then get replies with ta_all_inform_result to caller. |
| `test_kv_editor.c` | KV editor page lists records; fwd/back moves the selection. |
| `test_log_accept.c` | Log accept fills a fixed buffer then rejects further lines. |
| `test_log_drain.c` | Log drain sends, clears even on 502, skips empty ticks inside 4:30. |
| `test_log_init.c` | Log init KV-gets log_receiver_url; inform installs the drain URL. |
| `test_mpd_net.c` | Integration: Router->MPD->Net poll cadence with reply_to/session_id. |
| `test_net_events.c` | Net dialect/poll/albumart with reply_to and fake backend seam. |
| `test_net_kv_http.c` | PUT /kv/KEY then exit-all+boot picks up the new actor blob. |
| `test_net_mpd.c` | MPD Net dialect: poll/set coalesce and albumart reply_to. |
| `test_net_sntp.c` | Net SNTP after_wifi seam is recorded for the timesource handoff. |
| `test_queue.c` | Multi-producer/single-consumer queue: peek/handle/pop, full-drop, shape lock. |
| `test_registry_logger.c` | Registry posts; Init list starts Logger; log sample/reject policies. |
| `test_router.c` | SetRoute(MPD) delivers events to MPD stub; Sonos stub stays quiet. |
| `test_sched_cadence.c` | Scheduler: 1Hz clock, title scroll ox, one-shots under fake time. |
| `test_sched_events.c` | Scheduler start/stop fires ticks with session_id under fake time. |
| `test_screenshots.c` | Pixel-perfect glass UI vs PNG goldens in ../screenshots/ (see file for golden refresh). |
| `test_shape_l2r.c` | Shapepack tag densities (6x5..3x10) and L2R width/height from children. |
| `test_shape_swap.c` | SwapShape binds n equal-size children and shows exactly one active. |
| `test_smoke.c` | Harness smoke: proves make test can run a host binary off-device. |
| `test_text.c` | ta_text_build turns ASCII+glyph map into a ShapeL2R pack+kern stream. |
| `test_uilayout.c` | UILayout 32-bit dirty/x/y/shape word; pack66 BitMap in the shape table. |
| `test_under_image.c` | Under-image policy: dirty base invalidates covering exteriors that must redraw. |
| `test_viewport.c` | Viewport ox scroll bakes child window; under-image buffer stays intact. |
| `test_wire.c` | fn_enum wire: nav select and swap step without function pointers on shapes. |
| `test_runtime_cfg.c` | Runtime KV settings: factory defaults load; override then reload. |

