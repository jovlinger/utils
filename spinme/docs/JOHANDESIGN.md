spinme mk 3
===========

This is the high-level design.

Our ESP32 has two cores.

# Core A responsibilities

Core A is UI only. It decodes screen press and the rotary encoder (count and
pool rotation clicks). It paints the screen. In response to user actions it
posts events to the event stream. Core A handles the whole rotary decode, even
if that means other parts of the UI are starved. A press is only (x, y). A does
not know about play/pause, Toggle, desired volume, or the player. Everything
else is Core B.

# Core B graphics

We maintain 2 framebuffers PANEL_W x PANEL_H x RGBA: curr and next. And a state
variable busy-by-core-A. Core A does not see next, so that always belongs to
Core B. curr is traded back and forth.

There is also a PANEL_H-bit dirty bitmap (one bit per row).

Core A has function redraw(), with busy-by-core-A set while A is pushing.

Core B prepares the framebuffers. next is the one B is drawing. curr is the one
installed for the panel. Depending on hardware, A can push whole rows or only
the dirty rows of curr.

Panel size, ring depth, clock tick, and scheduler periods are implementation
constants. Current Waveshare settings live in spinme/DESIGN.md.

# Core B events

Core B is an asynchronous event stream handler. Events are structs: tagged
unions. Each carries the data it needs. To process the queue, we peek an event
(the queue is a circular list of event structs by value, so this is a pointer
into the ring, or zero for none). If we get an event, we process it with the
event handler, one big switch on the selector. Then we pop. Events are the unit
of locking. So all mutation, or reads that require a uniform view, must go
through events. No locks.

The event queue is a circular list of event structs (QUEUE_DEPTH). When we push,
we write into the slot at the tail and then advance the tail. We peek, then
handle, then pop, so we own the slot while processing.

A function selector is a small int enum. It indexes into a switch dispatch.
That is the only meaning of "dispatch" here: not a function pointer.

Examples from the front end:

- screen press: int x, y
- volume / rotation: pooled clicks from A (B owns desired and the player write)
- screen on
- screen off

Each of these wakes the interruptible sleep in the Core B loop below.

We skip invalidate as an event. Dirty lives on the shape; update/render consume
it.

Examples from the scheduler:

- update / render (see Graphics)
- redraw screen

# B Schedulers

Core B has a list of schedulers. For each iteration around the loop, each
scheduler item (also a tagged union with a function selector) is processed in
turn by the schedule handler, which is also a big switch.

Example schedulers:

- All: every scheduler has last_run and every, in clock ticks. When
  last_run + every < now, it is overdue and we run. Update last_run
  optimistically before the push.
  - Most schedulers are permanent. These do not go away.
  - There is a second short list of one-off schedulers. Front-packed and
    zero-terminated: when one inner item has expired, move the tail item into
    its space and zero the tail. Each has every and expire_by. Most often the
    same, but they can differ.
  - Each scheduler does exactly one thing: it pushes an event into the event
    queue. Overflow is logged ERROR. Most events are missable and idempotent
    (HICAP to verify that property for each selector).

- update_render_draw. One large function preferred: update the zlist, render
  into next, then (when A is free) compare, swap, and ping Core A.redraw().
  every is UPDATE_RENDER_EVERY (tweakable; current setting 200 ms). It can be
  split into separate events later. If A is busy at the ping step, one-off
  schedule a redraw retry in REDRAW_RETRY_EVERY, attempt += 1, log ERROR at
  REDRAW_ATTEMPT_CAP.

- clock. Enqueue update of logical seconds and absolute tick.

- player poll. Refresh player variables over the net (Volumio; Sonos similar).
  Hiding poll latency behind the ring is later.

# B loop

The core loop is:

- peek event
  - if not none: handle, then pop
- run schedulers -> next run delay
- interruptible sleep until now + next run delay

# Graphics

Each shape is a tagged union struct. Shapes live in an explicit zlist. The
zlist and the exterior boxes are built once at startup. Update must not change
layout position or exterior.

A function selector is a small int enum on the shape. Update dispatch is a
switch on that selector. Same rule as events and schedulers: no function
pointers.

Prefer one large function: update, then render into next, then ping Core A to
draw (compare, swap when free, A.redraw()). Split into separate events only if
needed later.

## Zlist and the child tree

The zlist is draw / hit order only. Index 0 is closest to the viewer. Draw
most distant first (high index down to 0). Hit-test closest first (0 upward).
Stay consistent with that; nothing else about the index convention matters.

A shape stores children only. There is no parent index. Child-dirty therefore
needs a recursive descent: walk children, then mark this shape dirty if any
child is dirty. That walk is useless on the naive path, but it is the hook
Cache will need later. Render and hit-test follow the zlist, not the child
tree. Update runs the per-shape selector; the recursive descent is for the
dirty mark over children.

## Two phases: update then render

Update and render are two phases. No Cache on this path. The whole backing
is redrawn from scratch every time. That is the baseline speed.

### Update

Update walks the zlist and modifies dynamic fields on each object. Examples:

- fixed: return, dirty stays false
- scroll: move the viewport origin
- clock text: rewrite the string to the current time

Whenever details are updated, set that shape's dirty bit. Also set dirty if any
child is dirty (recursive descent over children; no parent link).

Update does not write pixels.

### Render

Render walks the zlist most distant first (high index to 0) and draws each
shape onto next. Drawing resets that shape's dirty bit.

Do not clear next first. The base layer is a normal shape (for now static
paper / backdrop). Later it may be a JPEG fetched and downsampled to
PANEL_W x PANEL_H. Shapes after it in the zlist draw over it. On this naive
path the base shape can be a full-buffer memcpy into next, then the rest draw.

Render has no Cache. Selective damage and Cache are later.

## Hit test

Hit test walks the zlist closest first (index 0 upward). Each shape has an
accept_hit bit. Caches will not accept hits. Return the first shape that
accepts a hit and whose exterior contains the point. HIT_OPAQUE_PCT is a tweakable constant; 0 means off. The base shape is the
bottom layer; nothing sits below it.

A posts press (x, y) only. B hit-tests. A transport hit enqueues Toggle (and
may enqueue Poll). Toggle sets the local play/pause mode used for drawing
(paused shows the play label) and sends the toggle command to the player.

## After render

Compare curr and next, fill the row dirty bitmap from the actual diff, swap
when A is free, and ping A.redraw().

# Out of this note

spinme/DESIGN.md holds constants, the follow-view picture, measured packing, and
queue samples. This file is the Core A / Core B and update/render sketch.
