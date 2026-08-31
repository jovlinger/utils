# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: initializedcheck=False
# cython: nonecheck=False
# cython: cdivision=True
"""Stacklang render VM ops: pixel loops, z-list composite, color_at surface lang."""

from libc.math cimport fabs, fmax, fmin, sqrt

from imgcomp._stack_c cimport (
    OpHandler,
    _handler,
    data_pop_float,
    data_push_float,
)
from imgcomp._stack_c import invoke_body_id
from imgcomp.stacklang_debug import log_c_to_py


cdef unsigned char[:] _pixels = None
cdef int _buf_width = 0
cdef int _buf_height = 0
cdef double _half_w = 0.0
cdef double _half_h = 0.0
cdef double _current_gy = 0.0
cdef object _tree = None
cdef list _layers = None
cdef list _layer_op_ids = None
cdef list _shape_objects = None
cdef int _num_layers = 0


def bind_render(
    pixels,
    int width,
    int height,
    object tree,
    list layers,
    list layer_op_ids,
    list shape_objects,
    int num_layers,
) -> None:
    """Attach surface, quadtree, scene layers, and per-layer VM op ids."""
    cdef unsigned char[:] view = pixels
    if view.shape[0] != width * height * 4:
        raise ValueError("pixel buffer size mismatch")
    global _pixels, _buf_width, _buf_height, _half_w, _half_h
    global _tree, _layers, _layer_op_ids, _shape_objects, _num_layers
    _pixels = view
    _buf_width = width
    _buf_height = height
    _half_w = width / 2.0
    _half_h = height / 2.0
    _tree = tree
    _layers = layers
    _layer_op_ids = layer_op_ids
    _shape_objects = shape_objects
    _num_layers = num_layers


cdef inline void write_rgba(int px, int py, unsigned char r, unsigned char g, unsigned char b, unsigned char a) noexcept:
    cdef int offset = (py * _buf_width + px) * 4
    _pixels[offset] = r
    _pixels[offset + 1] = g
    _pixels[offset + 2] = b
    _pixels[offset + 3] = a


cdef inline unsigned char clamp_u8(double value) noexcept:
    if value <= 0.0:
        return 0
    if value >= 255.0:
        return 255
    return <unsigned char>int(value + 0.5)


cdef inline void push_rgba_float(double r, double g, double b, double a) except *:
    data_push_float(r)
    data_push_float(g)
    data_push_float(b)
    data_push_float(a)


cdef inline void pop_rgba_float(double* r, double* g, double* b, double* a) except *:
    a[0] = data_pop_float()
    b[0] = data_pop_float()
    g[0] = data_pop_float()
    r[0] = data_pop_float()


cdef inline void src_over(
    double sr,
    double sg,
    double sb,
    double sa,
    double dr,
    double dg,
    double db,
    double da,
    double* or_,
    double* og,
    double* ob,
    double* oa,
) noexcept:
    cdef double src_a
    cdef double dst_a
    cdef double out_a
    if sa <= 0.0:
        or_[0] = dr
        og[0] = dg
        ob[0] = db
        oa[0] = da
        return
    if sa >= 255.0:
        or_[0] = sr
        og[0] = sg
        ob[0] = sb
        oa[0] = sa
        return
    src_a = sa / 255.0
    dst_a = da / 255.0
    out_a = src_a + dst_a * (1.0 - src_a)
    if out_a <= 0.0:
        or_[0] = 0.0
        og[0] = 0.0
        ob[0] = 0.0
        oa[0] = 0.0
        return
    or_[0] = (sr * src_a + dr * dst_a * (1.0 - src_a)) / out_a
    og[0] = (sg * src_a + dg * dst_a * (1.0 - src_a)) / out_a
    ob[0] = (sb * src_a + db * dst_a * (1.0 - src_a)) / out_a
    oa[0] = out_a * 255.0


cdef inline int shape_index() except -1:
    cdef int idx = <int>data_pop_float()
    if idx < 0 or idx >= len(_shape_objects):
        raise IndexError("shape index out of range")
    return idx


cdef inline void invoke_rgba_at(double gy, double gx, int op_id, double* r, double* g, double* b, double* a) except *:
    cdef double drop_gx
    cdef double drop_gy
    data_push_float(gy)
    data_push_float(gx)
    invoke_body_id(op_id)
    pop_rgba_float(r, g, b, a)
    drop_gx = data_pop_float()
    drop_gy = data_pop_float()


cdef int _op_slr_dup_anchor_push_xy() except -1:
    """Stack gy gx dist -- gy gx dist gy gx . Duplicate anchor under distance."""
    cdef double dist = data_pop_float()
    cdef double gx = data_pop_float()
    cdef double gy = data_pop_float()
    data_push_float(gy)
    data_push_float(gx)
    data_push_float(dist)
    data_push_float(gy)
    data_push_float(gx)


cdef int _op_slr_float_max2() except -1:
    """Stack gy gx d1 d2 -- gy gx max(d1, d2) ."""
    cdef double d2 = data_pop_float()
    cdef double d1 = data_pop_float()
    data_push_float(fmax(d1, d2))


cdef int _op_slr_offset_xy_sub() except -1:
    """Stack gy gx gy gx tx ty -- gy gx gy' gx' . Subtract tx,ty from top coords."""
    cdef double ty = data_pop_float()
    cdef double tx = data_pop_float()
    cdef double gx = data_pop_float()
    cdef double gy = data_pop_float()
    data_push_float(gy - ty)
    data_push_float(gx - tx)


cdef int _op_slr_rgba_solid_if_hit() except -1:
    """Stack gy gx cr cg cb ca sr sg sb sa -- gy gx r g b a .

    If child alpha > 0, push solid (sr,sg,sb,sa); else transparent.
    """
    cdef double sa = data_pop_float()
    cdef double sb = data_pop_float()
    cdef double sg = data_pop_float()
    cdef double sr = data_pop_float()
    cdef double ca = data_pop_float()
    cdef double cb = data_pop_float()
    cdef double cg = data_pop_float()
    cdef double cr = data_pop_float()
    cdef double gx = data_pop_float()
    cdef double gy = data_pop_float()
    data_push_float(gy)
    data_push_float(gx)
    if ca > 0.0:
        push_rgba_float(sr, sg, sb, sa)
    else:
        push_rgba_float(0.0, 0.0, 0.0, 0.0)


cdef int _op_slr_dup_xy() except -1:
    """Stack gy gx -- gy gx gy gx . Copy coords for later restore."""
    cdef double gx = data_pop_float()
    cdef double gy = data_pop_float()
    data_push_float(gy)
    data_push_float(gx)
    data_push_float(gy)
    data_push_float(gx)


cdef int _op_slr_circle_distance() except -1:
    """Stack gy gx gy gx radius -- gy gx dist ."""
    cdef double radius = data_pop_float()
    cdef double gx = data_pop_float()
    cdef double gy = data_pop_float()
    cdef double dist = sqrt(gx * gx + gy * gy) - radius
    data_push_float(dist)


cdef int _op_slr_rectangle_distance() except -1:
    """Stack gy gx gy gx half_w half_h -- gy gx dist ."""
    cdef double half_h = data_pop_float()
    cdef double half_w = data_pop_float()
    cdef double gx = data_pop_float()
    cdef double gy = data_pop_float()
    cdef double qx = fabs(gx) - half_w
    cdef double qy = fabs(gy) - half_h
    cdef double outside = sqrt(fmax(qx, 0.0) * fmax(qx, 0.0) + fmax(qy, 0.0) * fmax(qy, 0.0))
    cdef double inside = fmin(fmax(qx, qy), 0.0)
    data_push_float(outside + inside)


cdef int _op_slr_oval_distance() except -1:
    """Stack gy gx gy gx radius_x radius_y -- gy gx dist ."""
    cdef double radius_y = data_pop_float()
    cdef double radius_x = data_pop_float()
    cdef double gx = data_pop_float()
    cdef double gy = data_pop_float()
    cdef double nx = gx / radius_x
    cdef double ny = gy / radius_y
    cdef double scale = fmin(radius_x, radius_y)
    cdef double dist = (sqrt(nx * nx + ny * ny) - 1.0) * scale
    data_push_float(dist)


cdef int _op_slr_fill_white() except -1:
    """Stack gy gx -- gy gx r g b a . Opaque WHITE everywhere."""
    cdef double gx = data_pop_float()
    cdef double gy = data_pop_float()
    data_push_float(gy)
    data_push_float(gx)
    push_rgba_float(255.0, 255.0, 255.0, 255.0)


cdef int _op_slr_rgba_transparent() except -1:
    """Stack gy gx -- gy gx r g b a . Push transparent accum onto stack."""
    cdef double gx = data_pop_float()
    cdef double gy = data_pop_float()
    data_push_float(gy)
    data_push_float(gx)
    push_rgba_float(0.0, 0.0, 0.0, 0.0)


cdef int _op_slr_src_over_layer() except -1:
    """Stack gy gx dr dg db da sr sg sb sa -- gy gx r g b a .

    Composite like ``src_over(dst, src)`` in ``imgcomp.rgba`` (member over accum).
    """
    cdef double sa = data_pop_float()
    cdef double sb = data_pop_float()
    cdef double sg = data_pop_float()
    cdef double sr = data_pop_float()
    cdef double da = data_pop_float()
    cdef double db = data_pop_float()
    cdef double dg = data_pop_float()
    cdef double dr = data_pop_float()
    cdef double gx = data_pop_float()
    cdef double gy = data_pop_float()
    cdef double out_r
    cdef double out_g
    cdef double out_b
    cdef double out_a
    src_over(sr, sg, sb, sa, dr, dg, db, da, &out_r, &out_g, &out_b, &out_a)
    data_push_float(gy)
    data_push_float(gx)
    push_rgba_float(out_r, out_g, out_b, out_a)


cdef int _op_slr_python_distance() except -1:
    """Stack gy gx gy gx shape -- gy gx dist . Slow path: shape.distance(gx, gy)."""
    cdef int idx = shape_index()
    cdef double gx = data_pop_float()
    cdef double gy = data_pop_float()
    cdef object shape = _shape_objects[idx]
    log_c_to_py("python_distance", idx=idx, gx=gx, gy=gy, shape=shape)
    cdef double dist = shape.distance(gx, gy)
    data_push_float(dist)


cdef int _op_slr_sdf_fill_white() except -1:
    """Stack gy gx dist -- gy gx r g b a . Opaque WHITE inside, transparent outside."""
    cdef double dist = data_pop_float()
    cdef double r = 0.0
    cdef double g = 0.0
    cdef double b = 0.0
    cdef double a = 0.0
    if dist <= 0.0:
        r = 255.0
        g = 255.0
        b = 255.0
        a = 255.0
    push_rgba_float(r, g, b, a)


cdef int _op_slr_python_color_at() except -1:
    """Stack gy gx shape -- gy gx r g b a . Slow path: shape.color_at(gx, gy)."""
    cdef int idx = shape_index()
    cdef double gx = data_pop_float()
    cdef double gy = data_pop_float()
    cdef object shape
    cdef object rgba
    cdef double r
    cdef double g
    cdef double b
    cdef double a
    shape = _shape_objects[idx]
    log_c_to_py("python_color_at", idx=idx, gx=gx, gy=gy, shape=shape)
    rgba = shape.color_at(gx, gy)
    if rgba is None:
        r = g = b = 0.0
        a = 0.0
    else:
        r = rgba[0]
        g = rgba[1]
        b = rgba[2]
        a = rgba[3]
    data_push_float(gy)
    data_push_float(gx)
    push_rgba_float(r, g, b, a)


cdef int _op_slr_set_gy() except -1:
    """Stack gy -- . Remember row gy for nested gx paint loops."""
    global _current_gy
    _current_gy = data_pop_float()


cdef int _op_slr_paint_pixel() except -1:
    """Stack gx -- . Z-list lookup at (_current_gy, gx), composite, paint."""
    cdef double gx = data_pop_float()
    cdef double gy = _current_gy
    cdef int px = <int>(gx + _half_w - 0.5)
    cdef int py = <int>(gy + _half_h - 0.5)
    cdef object z_list
    cdef int layer_index
    cdef int op_id
    cdef double ar = 0.0
    cdef double ag = 0.0
    cdef double ab = 0.0
    cdef double aa = 0.0
    cdef double lr
    cdef double lg
    cdef double lb
    cdef double la
    cdef double out_r
    cdef double out_g
    cdef double out_b
    cdef double out_a
    if px < 0 or py < 0 or px >= _buf_width or py >= _buf_height:
        return 0
    log_c_to_py("z_list_at_point", gx=gx, gy=gy, px=px, py=py)
    z_list = z_list_at_point(_tree, gx, gy)
    present = {layer.index for layer in z_list}
    for layer_index in range(_num_layers - 1, -1, -1):
        if layer_index not in present:
            continue
        op_id = _layer_op_ids[layer_index]
        invoke_rgba_at(gy, gx, op_id, &lr, &lg, &lb, &la)
        src_over(lr, lg, lb, la, ar, ag, ab, aa, &out_r, &out_g, &out_b, &out_a)
        ar = out_r
        ag = out_g
        ab = out_b
        aa = out_a
        if aa >= 255.0:
            break
    write_rgba(px, py, clamp_u8(ar), clamp_u8(ag), clamp_u8(ab), clamp_u8(aa))
    return 0


def z_list_at_point(object tree, double gx, double gy):
    from imgcomp.stacklang_render import z_list_at_point as _z_list_at_point

    return _z_list_at_point(tree, gx, gy)


slr_set_gy = _handler(_op_slr_set_gy)
slr_dup_xy = _handler(_op_slr_dup_xy)
slr_dup_anchor_push_xy = _handler(_op_slr_dup_anchor_push_xy)
slr_float_max2 = _handler(_op_slr_float_max2)
slr_offset_xy_sub = _handler(_op_slr_offset_xy_sub)
slr_rgba_solid_if_hit = _handler(_op_slr_rgba_solid_if_hit)
slr_circle_distance = _handler(_op_slr_circle_distance)
slr_rectangle_distance = _handler(_op_slr_rectangle_distance)
slr_oval_distance = _handler(_op_slr_oval_distance)
slr_fill_white = _handler(_op_slr_fill_white)
slr_rgba_transparent = _handler(_op_slr_rgba_transparent)
slr_src_over_layer = _handler(_op_slr_src_over_layer)
slr_sdf_fill_white = _handler(_op_slr_sdf_fill_white)
slr_python_distance = _handler(_op_slr_python_distance)
slr_python_color_at = _handler(_op_slr_python_color_at)
slr_paint_pixel = _handler(_op_slr_paint_pixel)
