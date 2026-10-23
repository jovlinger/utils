# Follow view and the two cores

The glass shows the active zone. The knob sets volume. Touch replaces the missing dial click. The picture is a uimk2 bitmap tree. LVGL is not on this path.

The UI core is synchronous: encoder and touch interrupts, and the panel bus. The async core owns the tree, the arena, the sockets, the timers, and both frame buffers. The samples below are the design. Host code still has the earlier two-queue model until that design is built.

## The glass

Waveshare ESP32-S3 knob, 360 by 360, round bezel. No hardware push-click. Volumio is the player. A follow-view detent changes volume. A scrolling-view detent scrolls. Touch on the transport button toggles play and stop.

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

Index 0 is null. One parent per composited node. Pixels are straight-alpha RGBA, 8 bits per channel, R then G then B then A. A sample outside the box is a miss. (0,0,0,0) inside the box is a real color. Buffers are row-major: index (y * w + x) * 4.

| Kind | Role |
|------|------|
| RGBA | Plain raster, or one child recomposed into px over paper. The root screen buffer is a Layout, not this. |
| Layout | Placed children {x, y, idx}, back to front. The root owns the screen buffer and the per-row overlap lists. |
| L2R | Children packed left to right, hsep between them, bottom-aligned. |
| T2B | Children packed top to bottom, vsep between them, centered on x. |
| Viewport | One child, origin (ox, oy). Pixel (vx, vy) reads the child at (vx + ox, vy + oy), clipped to the viewport. |
| Glyph | Flash coverage. White RGB. Alpha is filled*255/64 from an 8 by 8 grid. Shared height H, baseline row B, tight ink width. |
| Cache | Foreground composited over a background into a caller-owned buffer. A sample reads that buffer and does not descend. It rebakes only when this node is marked dirty. A child invalidate stops at the Cache. |

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

Cache arm: uint16 bg, uint16 fg, pad, uint8 *px.

## How a frame is built

```
root   = Layout 360 x 360, px = the buffer being drawn, paper = black
button = RGBA, white, size = max(play, stop) + pad
play   = Cache("play",  ink = black, paper = white)
stop   = Cache("stop",  ink = black, paper = white)
zone   = Cache("spinme", ink = yellow, paper = black)
vol    = Cache(three widest digits, ink = white, paper = black)
desire = Cache(three widest digits, ink = cyan, paper = clear)
desire.combiner = SCALE alpha 128
seal the arena                         # static_top

artist, album = Cache lines at album_mark
mark song
title = Cache line at song_mark

place, top to bottom:
  button at ((360 - button.w) / 2, 8)
  the shown label centered inside the button
  zone, artist, album, title, vol at x = 24
  desire at vol's box only while desire != vol
```

A line is one arena block: a zero-terminated uint16 index list, aligned to 4, then a paper raster, then the stored picture. The Cache's foreground is an L2R of one Glyph per codepoint. hsep is 1. The L2R combiner tints the white glyphs. Repaint bakes foreground over paper into the store. A later sample of a clean Cache copies the store.

```
bake(cache):
  if cache is not dirty: return
  for each pixel in cache.damage:
    acc = 0
    if fg covers the pixel: blend fg in front
    if acc.a < 255 and bg covers it: blend bg behind
    if acc.a == 0: store transparent
    else: store acc
  clear dirty
```

Scroll of a viewport adds (dx, dy) to the origin, clamped to int16, and invalidates the whole viewport with geometry false. It does not rewind, does not rebuild the index list, and does not mark the line Cache dirty. The viewport reads stored line pixels. There is no memmove on this path.

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
arena block, one allocation, 15444 bytes

  0     50   uint16 index[25]   24 glyph headers, then 0
  50     2   pad to 4
  52   7696   paper RGBA        148 * 13 * 4
7868   7696   Cache store       148 * 13 * 4
```

One store row is 148 * 4 = 592 contiguous bytes. Glyph coverage stays in flash: width * 13 bytes per glyph, not RGBA. The bitmap table takes 27 headers for this line: the Cache, the paper RGBA, the L2R, and 24 Glyphs. Those headers are the table, not this block. On the host each header is 80 bytes.

Marking the title dirty rebakes this store from the glyphs and the paper. A child invalidate does not. A scroll of a viewport over this Cache does not.

## Two cores

```
encoder IRQ ----+
touch IRQ ------+--> UI core ---- posts events ----> async queue
                |         ^                              |
                |         | done bit                     | compose next
                |         | dirty-line bits              | sockets, timers
                +---- panel bus <--- curr ---------------+
                              next is the other buffer
```

curr is the buffer sent to the panel. next is the buffer being drawn. Async is the only writer of next. The UI core is the only writer of the panel bus.

```
struct event {
  const char *name;          /* debug */
  void (*fn)(void *arg);
  void *arg;                 /* a struct when the call needs more */
};
```

A timer event, and pooled volume, are not enqueued when that function is already on the queue. Toggle always appends.

The UI core posts only:

- rotation: a decoded detent
- touch: x, y
- volume: the absolute level a follow-view detent is aiming at, pooled

Async hit-tests touch against the layout boxes of curr. The pixels are not the map. A hit on the transport button appends Toggle.

```
async, after composing next:
  set the dirty bits of the rows just written
  if done == 0: return          # UI still owns the bus; keep drawing next
  swap curr, next
  done = 0
  signal the UI core            # one trigger: a new buffer

UI refresh, when the bus is free:
  if done == 1: return          # nothing new to push
  for each set bit in the dirty vector of curr:
    push that row, clipped to the bezel
  clear those bits
  done = 1                      # async may flip again
```

Async keeps filling the new next while done is 0. That overlaps compose with the push. The push waits until a flip has cleared done, so it never sends a half-drawn buffer. The dirty vector is 360 bits, 45 bytes, one bit per row.

## Sample queue

Start: screen off, queue empty, done = 1.

Wake, from a detent at t = 0. The UI core arms the timers and posts one Poll. Desired becomes 41. Volume is pooled.

```
queue: [ poll ]
done:  1
```

Poll runs. The socket is slow. Before it returns, another detent aims at 42. Volume replaces nothing yet, because volume is not on the queue. The UI core posts it. A second detent to 43 replaces that entry in place. The poll stays in front.

```
queue: [ poll, volume(43) ]
done:  1
```

Poll returns the old snapshot, volume 40, title unchanged. Async writes the real digits "040" into next, sets those rows dirty, sees done, flips, clears done, signals. The UI core pushes those rows and sets done. Volume(43) then runs: desired digits "043" at alpha 128 over the real digits, dirty the same rows, flip, signal, push. The panel never waited on the socket.

A second poll timer fire while a poll is already queued does not grow the queue.

```
queue: [ poll ]          # the armed timer sees poll already there and skips
```

Touch at (180, 20), on the button, and a second touch before the first is handled. Touch is not exclusive. Async hit-tests each point against curr's layout. Each hit appends Toggle.

```
queue: [ touch(180,20), touch(180,22), toggle, toggle ]
```

Title longer than the viewport. The scroll timer is exclusive.

```
queue: [ scroll(title) ]
```

It steps the viewport by one pixel, or it re-lays the characters. Either way it marks the title Cache dirty, rebakes that store into next, sets the title's rows in the bitvector, and flips when done is set. A second scroll tick while scroll is queued does not enqueue another.

Screen-on is 30s. When it fires, the backlight goes off and the poll timer is removed. A snapshot that arrives in the dark updates next and does not signal the panel. A detent or a touch is what arms the poll timer again, at a 1s gap. The gap doubles after each idle fire, up to 16s.

## Out of scope

Greenthreads. The queue is the channel. LVGL. A primitive-id scanline pass. Memmove of a scrolled line, and a y-major pixel order.
