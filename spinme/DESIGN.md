# Follow view and the two cores

The glass shows the active zone. The knob sets volume. Touch replaces the missing dial click. The picture is a uimk2 shape set in an explicit zlist. LVGL is not on this path.

Core A is UI only: touch, rotary count and pooled rotation clicks, and painting the panel. Everything else is Core B, including the player. There are two framebuffers. The samples below are the design. Host code still has the earlier two-queue model until that design is built.

## Constants

Panel size, ring length, the clock tick, and the scheduler periods are implementation constants. The loops use the names. A board file sets the values. Changing a value does not change the control flow.

| Name | Meaning | Current Waveshare setting |
|------|---------|---------------------------|
| PANEL_W | framebuffer width in pixels | 360 |
| PANEL_H | framebuffer height in pixels | 360 |
| QUEUE_DEPTH | event-ring slots | 8 |
| CLOCK_RES | one tick of the absolute clock | 1 ms |
| CLOCKS_PER_SEC | ticks in one logical second | 1000 |
| POLL_EVERY_START | poll gap armed on wake | 1 s |
| POLL_EVERY_MAX | poll gap cap | 16 s |
| SCREEN_OFF_EVERY | backlight-off delay | 30 s |
| UPDATE_RENDER_EVERY | update_render_draw cadence while awake | 200 ms |
| REDRAW_RETRY_EVERY | delay before a busy redraw is retried | 50 ms |
| REDRAW_ATTEMPT_CAP | busy redraws before ERROR | 5 |
| HIT_OPAQUE_PCT | min opacity percent for an opaque hit (0 = off) | 0 |

`last_run`, `every`, and `expire_by` count CLOCK_RES ticks. Each framebuffer is PANEL_W by PANEL_H, PANEL_W * PANEL_H * 4 bytes. The dirty bitmap is PANEL_H bits, one per row, filled only by comparing curr to next.

## The glass

Waveshare ESP32-S3 knob, round bezel. No hardware push-click. Volumio is the player. A follow-view detent changes volume. A scrolling-view detent scrolls. Touch on the transport button toggles play and stop.

```
          +----------------------+
          |      play / stop     |   y = 8, centered
          +----------------------+   wider of the two labels, pad 12 x 6
          spinme                     x = 24, yellow ink
          Artist                     album region, white ink
          Album
          The Long Track Name.flac   title, at song_mark
          010                        three digits
          011                        desired, same box, alpha 128, only
                                     while it differs from the polled digits
```

Zone, the button, and the digits are fixed slots below static_top. Artist then album sit in the album region. The title sits at song_mark. A title-only change rewinds to song_mark and leaves the artist bytes in place.

## Types

Index 0 is null. One parent per composited node. Each shape is a tagged union. Pixels are straight-alpha RGBA, 8 bits per channel, R then G then B then A. A sample outside the box is a miss. (0,0,0,0) inside the box is a real color. Buffers are row-major: index (y * w + x) * 4.

| Kind | Role |
|------|------|
| RGBA | Plain raster, or one child recomposed into px over paper. The root screen buffer is a Layout, not this. |
| Layout | Placed children {x, y, idx}, back to front. The root owns the screen buffer and the per-row overlap lists. |
| L2R | Children packed left to right, hsep between them, bottom-aligned. |
| T2B | Children packed top to bottom, vsep between them, centered on x. |
| Viewport | One child, origin (ox, oy). Pixel (vx, vy) reads the child at (vx + ox, vy + oy), clipped to the viewport. |
| Glyph | Flash coverage. White RGB. Alpha is filled*255/64 from an 8 by 8 grid. Shared height H, baseline row B, tight ink width. |
| Cache | Reserved. A stored foreground over a background. Not used on the naive path. Kept in the kind set so scroll dirty and child invalidate have a place to stop later. |

A combiner is {mask, op, value[4]}. mask bits are R=1, G=2, B=4, A=8. SET stores v. SCALE is c * v / 255, rounded. CURVE is c + (v - 128) * c * (255 - c) / 32768, with 0 and 255 fixed and v = 128 the identity. The combiner runs on a sample before it blends into its parent.

Header fields, in order. Offsets are the host ABI (8-byte pointers), measured on this machine. The device has 4-byte pointers, so the union starts earlier there. The arena bytes below do not depend on that.

```
offset  size  field
0       1     kind
1       1     dirty
2       1     geom_dirty
3       1     combiner
4       8     damage {int16 x, y; uint16 w, h}
12      2     parent
14      2     w
16      2     h
18      6     pad to the pointer alignment
24      56    union (rgba / layout / pack / viewport / glyph / cache)
              host sizeof(uimk2_bm) = 80
```

Cache arm (reserved): uint16 bg, uint16 fg, pad, uint8 *px.

A shape update, an event, and a scheduler each carry a function selector. See Function selector.

## How a frame is built

```
root   = Layout PANEL_W x PANEL_H, px = next, paper = black
button = RGBA, white, size = max(play, stop) + pad
play   = line("play",  ink = black, paper = white)
stop   = line("stop",  ink = black, paper = white)
zone   = line("spinme", ink = yellow, paper = black)
vol    = line(three widest digits, ink = white, paper = black)
desire = line(three widest digits, ink = cyan, paper = clear)
desire.combiner = SCALE alpha 128
seal the arena                         # static_top

artist, album = lines at album_mark
mark song
title = line at song_mark

place, top to bottom:
  button at ((PANEL_W - button.w) / 2, 8)
  the shown label centered inside the button
  zone, artist, album, title, vol at x = 24
  desire at vol's box only while desire != vol
```

A line is an L2R of one Glyph per codepoint, hsep 1, with paper behind. The L2R combiner tints the white glyphs. This pass paints those children live into next. A later Cache wrapper may store a baked line; that is not required now.

## Update then render

Shapes live in an explicit zlist. The zlist and exterior boxes are built once at startup. Update and render both follow that list. A function selector is a small int enum; dispatch is a switch. Invalidate is not an event.

Prefer one large function: update, render into next, then ping Core A to draw (compare, swap when free, A.redraw()).

The zlist is draw / hit order. Index 0 is closest. Draw most distant first (high index to 0). Hit-test closest first (0 upward). A shape stores children only; there is no parent index. Child-dirty is a recursive descent over children.

### Update

Update runs the per-shape selector and changes dynamic fields only. Layout position and exterior cannot change here.

```
update(shape):
  switch shape.update_selector:
    fixed:     return
    scroll:    step the viewport origin
    clocktext: rewrite the string from the clock
    ...
  if details changed: shape.dirty = true

mark_dirty_from_children(shape):
  for c in shape.children:
    mark_dirty_from_children(c)
  if any child is dirty: shape.dirty = true
```

Child-dirty is useless on the naive path. It is the hook Cache will need later. Update does not write pixels.

### Render

Render walks the zlist most distant first into next. Baseline: redraw the whole backing from scratch. No Cache. No clear of next first. The base layer is a normal shape (static for now; later a JPEG downsampled to PANEL_W x PANEL_H). On the naive path that shape may be a full-buffer memcpy into next; closer shapes draw over it. Drawing a shape resets its dirty bit.

```
update_render_draw():
  for shape in zlist: update(shape)
  for root in roots: mark_dirty_from_children(root)
  for i from len(zlist)-1 down to 0:
    paint(zlist[i], zlist[i].pos, next)
    zlist[i].dirty = false
  if busy-by-core-A: schedule redraw retry; return
  compare curr and next; set row dirty bits
  if any bit set:
    swap curr and next
    busy-by-core-A = 1
    ping A.redraw()

paint(shape, offset, base):
  box = shape.bounds translated by offset
  overlap = intersection(box, base.bounds)
  for each pixel in overlap:
    write that pixel of shape into base
```

Scroll is an update arm. It does not rewind and does not rebuild an index list. The viewport origin moves; the next render shows the new pixels. There is no memmove of line pixels on this path.

### Hit test

Walk the zlist closest first (index 0 upward). Return the first shape with accept_hit set whose exterior contains the point. Caches will not accept hits. If HIT_OPAQUE_PCT is non-zero, also require the sample at that point to be at least that opaque. The base shape is the bottom layer; nothing sits below it.

## A 24-character title

The string is `The Long Track Name.flac` (24 bytes, 24 codepoints). Helvetica at 12 px from the host generator: every glyph is 13 rows, baseline on row 10. Widths, then one pixel of hsep after every glyph but the last:

```
T 7   h 6   e 6   sp 3
L 6   o 6   n 6   g 6   sp 3
T 7   r 3   a 6   c 6   k 5   sp 3
N 7   a 6   m 9   e 6
. 2   f 3   l 1   a 6   c 6
```

Ink is 125 pixels wide. Twenty-three separators add 23. The line is 148 by 13.

```
measured host line with a Cache wrapper (later form), 15444 bytes

  0     50   uint16 index[25]   24 glyph headers, then 0
  50     2   pad to 4
  52   7696   paper RGBA        148 * 13 * 4
7868   7696   Cache store       148 * 13 * 4
```

One store row is 148 * 4 = 592 contiguous bytes. Glyph coverage stays in flash: width * 13 bytes per glyph, not RGBA. With a Cache wrapper the table takes 27 headers for this line: the Cache, the paper RGBA, the L2R, and 24 Glyphs. On the host each header is 80 bytes. This pass may paint the L2R live and skip the store; the layout above is the budget when Cache is turned on.

## Two cores

```
encoder IRQ ----+
touch IRQ ------+--> Core A ---- posts event values ----> Core B ring
                |         ^                                  |
                |         | busy-by-core-A                   | schedulers
                |         | dirty-line bits                  | update / render
                +---- panel bus <--- curr                    | paint into next
                                  next belongs only to B
```

Core A is UI only. It decodes a screen press and the whole rotary (count and pool rotation clicks) even when that starves the rest of its work. It posts press (x, y) and pooled rotation/volume messages to B. It does not know about play/pause, Toggle, or the player. Desired volume and the player write live on B. A runs `redraw`. It does not see next, does not composite, does not hit-test, and does not open a player socket.

Two framebuffers. `curr` and `next` are their names. Swap exchanges the names. `curr` is the one installed for the panel. `next` is the one B is drawing, and the root layout's px. A does not see next. `busy-by-core-A` is set while A is pushing curr. While it is set, B draws into next, the other of the two. Swap waits until busy is clear.

The dirty bitmap is PANEL_H bits, one per row. Paint does not set those bits. Redraw fills them by comparing curr to next.

## Function selector

An event, a scheduler, and a shape update each carry a function selector: a small int enum that indexes into a switch. That is the only meaning of dispatch here.

## Event queue

An event is a tagged union, stored by value in a ring of QUEUE_DEPTH slots. The selector is the enum. A push writes the struct at the tail and then advances the tail. A pop advances the head. Peek returns a pointer into the ring, or zero when the ring is empty. The handler runs on that pointer, and only then does pop run, so the slot stays owned for the whole handler.

```
struct event {
  uint8_t selector;
  union {
    struct { int x, y; } press;
    struct { int new_val; } volume;
    struct { int attempt; } redraw;
    /* screen_on, screen_off, render, clock, player_poll: selector only */
  };
};

handle(event):
  switch event.selector:
    press:              hit-test (x, y) down the zlist
    volume:             set desired from A's pooled clicks; B may command the player
    toggle:             set local play/pause and command the player
    screen_on:          backlight on, arm the poll and screen-off schedulers
    screen_off:         backlight off, stop the poll scheduler
    update_render_draw: update, render into next, ping A when free
    redraw:             retry the compare/swap/ping if A was busy
    clock:              store the logical second and the absolute tick
    player_poll:        refresh player variables over the net
```

Invalidate is not an event. Dirty lives on the shape; update and render consume it.

A press is only (x, y). B hit-tests. A transport hit enqueues Toggle (and may enqueue Poll). Toggle sets the local play/pause mode used for drawing (paused shows the play label) and sends the toggle command to the player.

An event is the unit of locking: a mutation, or a read that has to be uniform, goes through the ring. There are no locks.

A full ring logs ERROR and does not store the new event. Most events are missable and idempotent. Hiding poll latency behind the ring is later.

Core A posts these, and each post wakes B's sleep:

- screen press: x, y
- volume / rotation: pooled clicks from A; B owns desired and the player write
- screen on
- screen off

B hit-tests a press down the zlist closest first: first accept_hit shape whose exterior contains the point. A hit on the transport button enqueues Toggle (and possibly Poll). A does not know that mapping.

## Schedulers

B keeps a list of schedulers. Each pass of the loop runs every scheduler through its function selector, the same way events are handled. A scheduler does one thing: it pushes one event.

Every scheduler has `last_run` and `every`, in CLOCK_RES ticks. When `last_run + every < now`, it is overdue and we run. It sets `last_run = now` before the push. Permanent schedulers stay on the list. A second, short list holds one-offs. That list is packed to the front and zero-terminated. Each one-off has `every` and `expire_by`. They are often equal. When one expires, the tail item moves into its slot and the tail is zeroed.

```
loop:
  e = peek()
  if e != 0:
    handle(e)
    pop()
  delay = run schedulers
  sleep until now + delay, interruptible by a post from A
```

Permanent schedulers:

- update_render_draw. Push the one large update / render / ping-A function. `every` is UPDATE_RENDER_EVERY. Zlist index 0 is closest.
- clock. Push the clock event.
- player poll. Push the poll event. `every` starts at POLL_EVERY_START on wake and doubles after each idle fire, up to POLL_EVERY_MAX. It is removed when the backlight goes off.

The screen-off scheduler is a one-off armed at wake with `expire_by` SCREEN_OFF_EVERY past now. It pushes `screen_off`. A detent or a press is what arms it again. A poll result does not.

If the ping step finds busy-by-core-A, arm a one-off that pushes `redraw` after REDRAW_RETRY_EVERY, attempt += 1, and log ERROR at REDRAW_ATTEMPT_CAP.

```
A.redraw():
  for each set bit:
    push that row of curr, clipped to the bezel
  clear the bits
  busy-by-core-A = 0
```

The bits are the actual pixel diff of the two finished framebuffers. A pushes curr only after that swap, so the rows on the bus are a finished framebuffer.

## Sample queue

Start: screen off, ring empty, busy clear.

A detent at t = 0. A pools the rotation and posts screen-on plus a volume message for B. B sets desired to 41 and may command the player. That wakes B.

```
ring: [ screen_on, volume(41) ]
busy: 0
```

`screen_on` arms poll at POLL_EVERY_START and screen-off at SCREEN_OFF_EVERY. The volume message is pooled clicks from A; B sets desired to 41. Render then paints next from scratch and pushes redraw.

```
ring: [ redraw(0) ]
```

Busy is clear, so redraw diffs, swaps, sets busy, and pings A. A pushes the dirty rows and clears busy.

The poll scheduler fires while a poll handler is still in the socket. A pools further clicks and messages B with 42, then 43. Two volume messages may sit behind the poll; the ring holds values, so 43 does not replace 42. B owns desired.

```
ring: [ player_poll, volume(42), volume(43) ]
```

The poll handler writes the real digits from the old snapshot. Each volume message updates desired on B. The last one leaves 43. The overlay is those digits at alpha 128 over the real digits. The panel push does not wait on the socket.

A push into a ring that already holds QUEUE_DEPTH events logs ERROR and is dropped. The dropped event is the one that did not fit.

A second poll tick pushes another poll only when the ring has a free slot. Two poll events are idempotent: the later snapshot wins.

Touch at (180, 20) and a second touch before the first is handled:

```
ring: [ press(180,20), press(180,22) ]
```

Each press is hit-tested. A hit on the transport button enqueues Toggle (and possibly Poll). The presses are both kept. When paused, render shows the play label.

The title is wider than its viewport. During update, the scroll arm steps the viewport origin and sets dirty. Render then draws the new origin. There is no scroll event on the ring.

A snapshot that arrives while the backlight is off updates next and does not ping A. A detent or a press arms the poll scheduler again at POLL_EVERY_START.

## Out of scope

Greenthreads. The ring is the channel. LVGL. A primitive-id scanline pass. Memmove of a scrolled line, and a y-major pixel order. Selective damage into next. Cache as an active compose path. Invalidate as an event. Recursive tree walk for update or render. Function pointers for dispatch.
