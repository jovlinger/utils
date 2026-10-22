# circui manual

This is how the host library actually behaves. It is the node struct,
the six constructors, `circui_sample`, `circui_render`, and `circui_hit`.
There is no widget set, no text, no frame clock, and no drag type.

A screen is a tree of nodes you allocate yourself. Constructors fill a
node you already own. They do not allocate, and they do not keep a
global list of nodes.

## The node

Every node is the same struct. The `sample` function pointer is the
kind. The other fields are storage that only some kinds read.

```text
node
  box            half-open rectangle, copied at construction
  color          rgba for rect, oval, and apply-color
  tx, ty         translation, in pixels
  child          one child, or null
  members        array of children, for a union
  member_count
  sample         which kind
  on_hit         optional callback
  user           pointer passed to that callback
```

A box is `[x, x+w)` by `[y, y+h)`. The origin is the top-left of the
backing store. x increases right, y increases down. A zero or negative
width or height is empty: nothing inside it samples, and nothing inside
it hits.

Color is straight RGBA, 8-bit channels, not premultiplied. Absence is
not a color. `(0,0,0,0)` is a real color a rect can write. A miss
writes nothing.

Constructors clear `tx`, `ty`, `child`, `members`, `member_count`,
`on_hit`, and `user`. Set the hit callback after you build the node.
Building again wipes it.

## Primitives

`rect(box, color)` is present on every pixel inside the box, in that
color.

`oval(box, color)` is present only on pixels inside both the box and
the ellipse inscribed in the box. The test uses the pixel center
`(x+0.5, y+0.5)`. The four corners of the box are absent.

Those two are leaves. They have no child.

## Composition

Four wrappers. Each one stores a box at the moment you build it. Later
changes to a child's box do not update the parent.

`apply_color(child, color)` is present where the child is present. The
sample is `color`, all four channels. The child's own color is ignored.
The stored box is a copy of the child's box.

`translate(child, tx, ty)` samples the child at `(x-tx, y-ty)`. The
stored box is the child box shifted by `(tx, ty)`. The sample function
itself does not re-check that box. `circui_render` and `circui_hit`
do, because they trust the stored box.

`clip(child, clip_box)` is present only where the point is inside
`clip_box` and the child is present. The stored box is `clip_box`, not
the intersection with the child. Coordinates are not shifted.

`union(members, count)` stores the axis-aligned bounds of the member
boxes that have positive area. Empty and null members are skipped while
computing that box. `members[0]` is the bottom. The last entry is the
top. The array must stay alive as long as you sample the union. The
node does not copy it.

A child pointer is not owned. Two parents may point at the same node.
A cycle does not terminate: sample and hit recurse with no visited set.

There is no rotation and no scale.

## What a widget is

Nothing in the library is a button, a label, or a scroller. A widget is
a node, or a small tree, plus a callback you attached.

A solid button is a rect, then `set_hit` on that rect. A tinted shape
is `apply_color` over an oval or a rect. A stack of those is a union.
A moving stack is a translate around a union, or a translate around
each piece before the union. Those are conventions. The library will
not invent them for you.

## Render order

`circui_render` does not clear the surface. It walks the stored box,
clipped to the surface, y from top to bottom and x from left to right
inside each row. For each pixel it samples the tree. A miss leaves the
bytes already in the buffer. A hit writes r, g, b, a in that order,
four bytes per pixel, row-major.

Sampling a union walks from the last member down to `members[0]`. It
composites as it goes. The accumulator starts transparent. Each present
layer is the destination, and the accumulator (everything already seen,
which is higher in the stack) is the source of a straight-alpha
src-over. So a higher member is painted over a lower one. An absent
member is skipped. When the accumulator alpha reaches 255, the walk
stops. Lower members are not sampled for that pixel. If no member was
present, or the accumulator alpha is 0, the pixel is a miss.

```text
members[0] = red,   opaque, box x=0..4
members[1] = blue,  alpha 128, box x=2..6

pixel 0  -> red
pixel 2  -> blue over red
pixel 5  -> blue
```

Src-over of an opaque source replaces the destination. Src-over of a
fully transparent source leaves the destination. Anything between
blends the channels by straight alpha and rounds to the nearest byte.

`apply_color`, `translate`, and `clip` sample their one child at the
coordinates described above. They do not reorder anything inside that
child. Order is entirely the union walk, repeated at every level.

## Hit order

`circui_hit(node, x, y)` returns 1 if some callback ran, otherwise 0.

If the point is outside the stored box, it misses, and children are
not asked. If `on_hit` is set, that callback runs and children are not
asked. The callback sees the coordinates this node saw, plus the
`user` pointer stored on the node.

If `on_hit` is null, the kind decides:

- translate: ask the child at `(x-tx, y-ty)`
- clip or apply-color: ask the child at `(x, y)`
- union: ask the last member first, then downward, and stop at the
  first child that returns 1
- rect or oval: nobody is asked, so the click is a miss unless you
  set `on_hit` on that leaf

A parent callback swallows the whole stored box, including holes where
the child would have sampled as absent. Hit uses the box, not the
sample.

```text
child  = rect at (0,0) size 4x4, on_hit = child_fn
parent = translate(child, 4, 1), on_hit = null

hit(parent, 5, 2)  -> child_fn(child, 1, 1)
hit(parent, 3, 2)  -> miss, outside the translated box

parent.on_hit = parent_fn
hit(parent, 5, 2)  -> parent_fn(parent, 5, 2)
                       child_fn does not run
```

## Presses and drags

A press is one call to `circui_hit` with the pointer coordinates. The
library does not store the last point, the pressed node, or a button
bit.

A drag is not a kind of node. Call `circui_hit` again on each move.
Each call is independent. If the point leaves the box, the call
misses, even if the press started inside. If you need the original
target to keep receiving the gesture, remember that node yourself and
call it, or call `circui_hit` on it, without asking the root again.

Do not put `on_hit` on a translate or a union if the thing you want to
drag is a descendant. The ancestor will consume the point and the
descendant will never see it. Leave those wrappers without a callback
so the translated point reaches the leaf, and put `on_hit` on the leaf.

There is no slider, no capture, and no distinction between press, move,
and release. Those are caller policy around `circui_hit`.

## Globals

There are none. No current tree, no clock, no arena, no pointer
position. The surface is an argument of `circui_render`. The only
mutable state is the memory you passed in: node fields, the members
array, the `user` objects, and the pixel buffer.

`sample` reads the tree and the coordinates. It does not write the
node. Two samples of an unchanged tree return the same presence and
the same color.

## Caching, and where it lies

The library keeps no raster cache and no dirty rectangle. Every
rendered pixel walks the tree again. The only skip inside that walk is
the union stopping when the accumulator is already opaque.

You can skip work outside the library because sampling is pure:

- An unchanged tree and an unchanged buffer need no second render.
- A changed subtree only affects pixels inside its stored box. Clear
  that rectangle yourself before re-rendering it. A miss does not erase
  the old pixel, so a second render on top of the first leaves stale
  ink in holes and in regions the new tree no longer covers.
- Two parents may share one subtree. That is the structural cache.
  There is no generation counter. If you mutate a shared child, both
  parents see it, and their stored boxes may now be wrong.

The stored box is a cache of the bounds, taken once. It can disagree
with what sampling would return:

- `circui_render` and `circui_hit` will not look outside the stored
  box. Grow a child after wrapping it and the new pixels are invisible
  and unclickable until you rebuild the parents.
- `circui_sample` on a translate or a union does not consult that box.
  A direct sample can still see a child pixel the render scan will
  never ask for.

Clip is the opposite shape of a tight bound. Its stored box is the
clip you passed, which may be larger than the child. Render will scan
the whole clip and sample the child on the holes.

## A small tree

```text
bottom = rect((0,0,4,4), opaque red)
top    = rect((2,0,4,4), half-blue)
stack  = union([bottom, top])
moved  = translate(stack, 20, 0)
view   = clip(moved, (0,0,8,8))
```

`render(moved)` writes red at `(20,0)` and leaves `(0,0)` untouched.
`render(view)` writes nothing: the translated stack sits at x=20, and
the clip box only covers x=0..8. `render(stack)` writes red at x=0,
the blend at x=2, and blue at x=5.

Rebuild `moved` if `stack`'s box changes. Do not expect `moved.box` to
follow on its own.
