#include "bitmap.h"

#include <string.h>

void bitmap_table_init(BitmapTable *t, Bitmap *storage, uint16_t cap) {
  memset(storage, 0, sizeof(*storage) * cap);
  t->b = storage;
  t->cap = cap;
  t->used = 1;
  t->samples = 0;
}

uint16_t bitmap_new(BitmapTable *t, BitmapKind kind, uint16_t w, uint16_t h) {
  if (t->used >= t->cap) {
    return 0;
  }
  uint16_t idx = t->used++;
  t->b[idx].kind = (uint8_t)kind;
  t->b[idx].w = w;
  t->b[idx].h = h;
  return idx;
}

bool bitmap_add(BitmapTable *t, uint16_t parent, uint16_t child, int16_t x,
                int16_t y) {
  Bitmap *p = &t->b[parent];
  if (t->b[child].parent != 0 || p->nitems >= p->items_cap) {
    return false;
  }
  p->items[p->nitems].x = x;
  p->items[p->nitems].y = y;
  p->items[p->nitems].idx = child;
  p->nitems++;
  t->b[child].parent = parent;
  return true;
}

bool bitmap_set_child(BitmapTable *t, uint16_t parent, uint16_t child) {
  if (t->b[child].parent != 0) {
    return false;
  }
  t->b[parent].child = child;
  t->b[child].parent = parent;
  return true;
}

/* Child i of a node as a LayoutItem in the node's coordinates. A Viewport
 * child sits at (-ox, -oy); an RGBA content child at (0, 0). */
static uint16_t child_count(const Bitmap *n) {
  switch (n->kind) {
    case BK_LAYOUT:
    case BK_L2R:
    case BK_T2B:
      return n->nitems;
    case BK_VIEWPORT:
    case BK_RGBA:
      return n->child ? 1 : 0;
    default:
      return 0;
  }
}

static LayoutItem child_item(const Bitmap *n, uint16_t i) {
  LayoutItem it = {0, 0, 0};
  if (n->kind == BK_VIEWPORT) {
    it.x = (int16_t)-n->ox;
    it.y = (int16_t)-n->oy;
    it.idx = n->child;
  } else if (n->kind == BK_RGBA) {
    it.idx = n->child;
  } else {
    it = n->items[i];
  }
  return it;
}

void bitmap_pack(BitmapTable *t, uint16_t idx) {
  Bitmap *n = &t->b[idx];
  int pos = 0;
  int cross = 0;
  for (uint16_t i = 0; i < n->nitems; i++) {
    const Bitmap *c = &t->b[n->items[i].idx];
    if (n->kind == BK_L2R) {
      n->items[i].x = (int16_t)pos;
      pos += c->w + n->hsep;
      if (c->h > cross) {
        cross = c->h;
      }
    } else {
      n->items[i].y = (int16_t)pos;
      pos += c->h + n->vsep;
      if (c->w > cross) {
        cross = c->w;
      }
    }
  }
  if (n->nitems > 0) {
    pos -= (n->kind == BK_L2R) ? n->hsep : n->vsep;
  }
  for (uint16_t i = 0; i < n->nitems; i++) {
    const Bitmap *c = &t->b[n->items[i].idx];
    if (n->kind == BK_L2R) {
      n->items[i].y = (int16_t)(cross - c->h); /* bottom: shared baseline */
    } else {
      n->items[i].x = (int16_t)((cross - c->w) / 2); /* center */
    }
  }
  if (n->kind == BK_L2R) {
    n->w = (uint16_t)pos;
    n->h = (uint16_t)cross;
  } else {
    n->w = (uint16_t)cross;
    n->h = (uint16_t)pos;
  }
}

static bool rect_empty(Rect r) { return r.w <= 0 || r.h <= 0; }

static Rect rect_union(Rect a, Rect b) {
  if (rect_empty(a)) {
    return b;
  }
  if (rect_empty(b)) {
    return a;
  }
  int x0 = a.x < b.x ? a.x : b.x;
  int y0 = a.y < b.y ? a.y : b.y;
  int x1 = (a.x + a.w) > (b.x + b.w) ? (a.x + a.w) : (b.x + b.w);
  int y1 = (a.y + a.h) > (b.y + b.h) ? (a.y + a.h) : (b.y + b.h);
  Rect r = {(int16_t)x0, (int16_t)y0, (int16_t)(x1 - x0), (int16_t)(y1 - y0)};
  return r;
}

static Rect rect_clip(Rect r, int w, int h) {
  int x0 = r.x < 0 ? 0 : r.x;
  int y0 = r.y < 0 ? 0 : r.y;
  int x1 = (r.x + r.w) > w ? w : (r.x + r.w);
  int y1 = (r.y + r.h) > h ? h : (r.y + r.h);
  Rect o = {0, 0, 0, 0};
  if (x1 > x0 && y1 > y0) {
    o.x = (int16_t)x0;
    o.y = (int16_t)y0;
    o.w = (int16_t)(x1 - x0);
    o.h = (int16_t)(y1 - y0);
  }
  return o;
}

void bitmap_invalidate(BitmapTable *t, uint16_t idx, Rect local_rect,
                       bool geometry) {
  Rect r = local_rect;
  while (idx != 0) {
    Bitmap *n = &t->b[idx];
    r = rect_clip(r, n->w, n->h);
    n->dirty = true;
    n->geom_dirty = n->geom_dirty || geometry;
    n->damage = rect_union(n->damage, r);
    uint16_t p = n->parent;
    if (p != 0) {
      const Bitmap *pn = &t->b[p];
      for (uint16_t i = 0; i < child_count(pn); i++) {
        LayoutItem it = child_item(pn, i);
        if (it.idx == idx) {
          r.x = (int16_t)(r.x + it.x);
          r.y = (int16_t)(r.y + it.y);
          break;
        }
      }
    }
    idx = p;
  }
}

/* acc is the layer on top; src goes under it. Straight-alpha src-over. */
static void blend_under(Px *acc, Px src) {
  if (acc->a == 255) {
    return;
  }
  uint32_t ta = acc->a;
  uint32_t sa = ((uint32_t)src.a * (255u - ta) + 127u) / 255u; /* src weight */
  uint32_t oa = ta + sa;
  if (oa == 0) {
    return;
  }
  acc->r = (uint8_t)(((uint32_t)acc->r * ta + (uint32_t)src.r * sa + oa / 2) / oa);
  acc->g = (uint8_t)(((uint32_t)acc->g * ta + (uint32_t)src.g * sa + oa / 2) / oa);
  acc->b = (uint8_t)(((uint32_t)acc->b * ta + (uint32_t)src.b * sa + oa / 2) / oa);
  acc->a = (uint8_t)oa;
}

/* Sample node idx at local (x, y) into acc, front to back. Returns true when
 * the node covers the point. Stops as soon as acc is opaque. */
static bool sample(BitmapTable *t, uint16_t idx, int x, int y, Px *acc) {
  const Bitmap *n = &t->b[idx];
  if (idx == 0 || x < 0 || y < 0 || x >= n->w || y >= n->h) {
    return false;
  }
  if (n->pixels) {
    t->samples++;
    blend_under(acc, n->pixels[y * n->w + x]);
    return true;
  }
  if (n->kind == BK_GLYPH) {
    t->samples++;
    Px p = {255, 255, 255, n->alpha[y * n->w + x]};
    blend_under(acc, p);
    return true;
  }
  bool covered = false;
  for (int i = (int)child_count(n) - 1; i >= 0 && acc->a != 255; i--) {
    LayoutItem it = child_item(n, (uint16_t)i);
    covered = sample(t, it.idx, x - it.x, y - it.y, acc) || covered;
  }
  return covered;
}

void bitmap_repaint(BitmapTable *t, uint16_t idx) {
  Bitmap *n = &t->b[idx];
  if (idx == 0 || !n->dirty) {
    return;
  }
  for (uint16_t i = 0; i < child_count(n); i++) {
    bitmap_repaint(t, child_item(n, i).idx);
  }
  if (n->pixels) {
    Rect d = rect_clip(n->damage, n->w, n->h);
    for (int y = d.y; y < d.y + d.h; y++) {
      for (int x = d.x; x < d.x + d.w; x++) {
        Px acc = {0, 0, 0, 0};
        for (int i = (int)child_count(n) - 1; i >= 0 && acc.a != 255; i--) {
          LayoutItem it = child_item(n, (uint16_t)i);
          sample(t, it.idx, x - it.x, y - it.y, &acc);
        }
        blend_under(&acc, n->paper); /* no child covered: paper */
        n->pixels[y * n->w + x] = acc;
      }
    }
    if (!rect_empty(d)) {
      n->repaints++;
    }
  }
  n->dirty = false;
  n->geom_dirty = false;
  memset(&n->damage, 0, sizeof(n->damage));
}
