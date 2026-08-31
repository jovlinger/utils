# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: initializedcheck=False
# cython: nonecheck=False
# cython: cdivision=True
"""Stacklang render VM ops: pixel loops, z-list composite, color_at surface lang."""

from libc.math cimport ceil, fabs, fmax, fmin, floor, sqrt

from imgcomp._stack_c cimport (
    OpHandler,
    _handler,
    data_peek_bottom_float,
    data_pop_float,
    data_push_float,
    data_push_int,
    data_pop_int,
)
from imgcomp._stack_c import invoke_body_id
from imgcomp.stacklang_debug import log_c_to_py


cdef unsigned char[:] _pixels = None
cdef int _buf_width = 0
cdef int _buf_height = 0
cdef double _half_w = 0.0
cdef double _half_h = 0.0
cdef double _current_gy = 0.0
cdef list _shape_objects = None


cdef struct CQuadNode:
    double xmin
    double ymin
    double xmax
    double ymax
    int member_ops_offset
    int first_child
    unsigned char member_op_count
    unsigned char _pad[7]


cdef const unsigned char[:] _quadtree_blob = None
cdef CQuadNode* _quad_nodes = NULL
cdef int _quad_node_count = 0
cdef const int* _leaf_op_ids = NULL
cdef int _leaf_op_count = 0

DEF _QTRE_MAGIC = 0x51545245
DEF _QTRE_VERSION = 2
DEF _QTRE_HEADER_SIZE = 16
DEF _QTRE_NODE_SIZE = 48


cdef void _release_quadtree() noexcept:
    global _quadtree_blob, _quad_nodes, _quad_node_count, _leaf_op_ids, _leaf_op_count
    _quadtree_blob = None
    _quad_nodes = NULL
    _quad_node_count = 0
    _leaf_op_ids = NULL
    _leaf_op_count = 0


cdef unsigned int _read_u32(const unsigned char[:] view, Py_ssize_t offset) noexcept:
    return (
        <unsigned int>view[offset]
        | (<unsigned int>view[offset + 1] << 8)
        | (<unsigned int>view[offset + 2] << 16)
        | (<unsigned int>view[offset + 3] << 24)
    )


cdef void _bind_quadtree_blob(object blob) except *:
    cdef const unsigned char[:] view = blob
    cdef unsigned int magic
    cdef unsigned int version
    cdef unsigned int node_count
    cdef unsigned int leaf_op_count
    cdef Py_ssize_t expected
    global _quadtree_blob, _quad_nodes, _quad_node_count, _leaf_op_ids, _leaf_op_count
    _release_quadtree()
    if view is None or view.shape[0] < _QTRE_HEADER_SIZE:
        raise ValueError("quadtree blob too small for header")
    magic = _read_u32(view, 0)
    version = _read_u32(view, 4)
    node_count = _read_u32(view, 8)
    leaf_op_count = _read_u32(view, 12)
    if magic != _QTRE_MAGIC:
        raise ValueError(f"bad quadtree magic: {magic:#x}")
    if version != _QTRE_VERSION:
        raise ValueError(f"unsupported quadtree version: {version}")
    expected = (
        _QTRE_HEADER_SIZE
        + <Py_ssize_t>node_count * _QTRE_NODE_SIZE
        + <Py_ssize_t>leaf_op_count * sizeof(int)
    )
    if view.shape[0] != expected:
        raise ValueError(f"quadtree blob size mismatch: {view.shape[0]} != {expected}")
    _quadtree_blob = view
    _quad_nodes = <CQuadNode*>(<char *>&view[0] + _QTRE_HEADER_SIZE)
    _quad_node_count = <int>node_count
    if leaf_op_count > 0:
        _leaf_op_ids = <const int*>(
            <char *>&view[0] + _QTRE_HEADER_SIZE + <Py_ssize_t>node_count * _QTRE_NODE_SIZE
        )
        _leaf_op_count = <int>leaf_op_count
    else:
        _leaf_op_ids = NULL
        _leaf_op_count = 0


cdef inline int _leaf_index_at_point(double gx, double gy) noexcept:
    cdef int node_idx = 0
    cdef CQuadNode node
    cdef CQuadNode child
    cdef int i
    cdef int child_idx
    if _quad_node_count == 0:
        return -1
    while True:
        node = _quad_nodes[node_idx]
        if node.first_child < 0:
            if node.member_op_count == 0:
                return -1
            return node_idx
        child_idx = -1
        for i in range(4):
            child = _quad_nodes[node.first_child + i]
            if (
                child.xmin <= gx <= child.xmax
                and child.ymin <= gy <= child.ymax
            ):
                child_idx = node.first_child + i
                break
        if child_idx < 0:
            return -1
        node_idx = child_idx


def bind_render(
    pixels,
    int width,
    int height,
    object quadtree_blob,
    list shape_objects,
) -> None:
    """Attach surface and mmap'd quadtree blob for C z-list compositing."""
    cdef unsigned char[:] view = pixels
    if view.shape[0] != width * height * 4:
        raise ValueError("pixel buffer size mismatch")
    global _pixels, _buf_width, _buf_height, _half_w, _half_h
    global _shape_objects
    _pixels = view
    _buf_width = width
    _buf_height = height
    _half_w = width / 2.0
    _half_h = height / 2.0
    _shape_objects = shape_objects
    _bind_quadtree_blob(quadtree_blob)


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
    cdef double gx = data_pop_float()
    cdef double gy = data_pop_float()
    data_push_float(gy)
    data_push_float(gx)
    data_push_float(fmax(d1, d2))


cdef int _op_slr_float_neg() except -1:
    """Stack d -- -d ."""
    cdef double d = data_pop_float()
    data_push_float(-d)


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


cdef int _op_slr_push_transparent_accum() except -1:
    """Stack gy gx -- gy gx 0 0 0 0 . Keep anchor xy, push transparent accum."""
    push_rgba_float(0.0, 0.0, 0.0, 0.0)


cdef int _op_slr_dup_anchor_xy() except -1:
    """Stack gy gx ... -- gy gx ... gy gx . Copy bottom anchor xy to top."""
    cdef double gy = data_peek_bottom_float(0)
    cdef double gx = data_peek_bottom_float(1)
    data_push_float(gy)
    data_push_float(gx)


cdef int _op_slr_drop_hit_xy() except -1:
    """Stack ... gy gx r g b a -- ... r g b a . Drop hit coords under top RGBA."""
    cdef double a = data_pop_float()
    cdef double b = data_pop_float()
    cdef double g = data_pop_float()
    cdef double r = data_pop_float()
    data_pop_float()
    data_pop_float()
    data_push_float(r)
    data_push_float(g)
    data_push_float(b)
    data_push_float(a)


cdef int _op_slr_src_over_layer() except -1:
    """Stack gy gx dr dg db da sr sg sb sa -- gy gx r g b a .

    Match ``src_over(layer, accum)`` in ``imgcomp.compound.Union.color_at``.
    """
    cdef double ma = data_pop_float()
    cdef double mb = data_pop_float()
    cdef double mg = data_pop_float()
    cdef double mr = data_pop_float()
    cdef double aa = data_pop_float()
    cdef double ab = data_pop_float()
    cdef double ag = data_pop_float()
    cdef double ar = data_pop_float()
    cdef double gx = data_pop_float()
    cdef double gy = data_pop_float()
    cdef double out_r
    cdef double out_g
    cdef double out_b
    cdef double out_a
    src_over(ar, ag, ab, aa, mr, mg, mb, ma, &out_r, &out_g, &out_b, &out_a)
    data_push_float(gy)
    data_push_float(gx)
    push_rgba_float(out_r, out_g, out_b, out_a)


cdef int _op_slr_anchorize_rgba() except -1:
    """Stack gy gx wy wx r g b a -- gy gx r g b a . Drop translated work coords."""
    cdef double a = data_pop_float()
    cdef double b = data_pop_float()
    cdef double g = data_pop_float()
    cdef double r = data_pop_float()
    data_pop_float()
    data_pop_float()
    push_rgba_float(r, g, b, a)


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


cdef int _op_slr_continue_if_not_opaque() except -1:
    """Stack gy gx dr dg db da -- gy gx dr dg db da flag .

    Push 1 when accum alpha < 255 (keep compositing), else 0.
    """
    cdef double da = data_pop_float()
    data_push_float(da)
    data_push_int(1 if da < 255.0 else 0)


cdef inline void _composite_leaf_pixel(
    double gy,
    double gx,
    CQuadNode* leaf,
    double* ar,
    double* ag,
    double* ab,
    double* aa,
) except *:
    cdef int member_index
    cdef int op_id
    cdef double lr
    cdef double lg
    cdef double lb
    cdef double la
    cdef double out_r
    cdef double out_g
    cdef double out_b
    cdef double out_a
    ar[0] = 0.0
    ag[0] = 0.0
    ab[0] = 0.0
    aa[0] = 0.0
    for member_index in range(leaf.member_op_count - 1, -1, -1):
        op_id = _leaf_op_ids[leaf.member_ops_offset + member_index]
        if op_id < 0:
            continue
        invoke_rgba_at(gy, gx, op_id, &lr, &lg, &lb, &la)
        src_over(lr, lg, lb, la, ar[0], ag[0], ab[0], aa[0], &out_r, &out_g, &out_b, &out_a)
        ar[0] = out_r
        ag[0] = out_g
        ab[0] = out_b
        aa[0] = out_a
        if aa[0] >= 255.0:
            break


cdef void _paint_leaf_cell(CQuadNode* leaf) except *:
    """Paint every pixel center inside a quadtree leaf AABB."""
    cdef int px_start
    cdef int px_end
    cdef int py_start
    cdef int py_end
    cdef int px
    cdef int py
    cdef double gx
    cdef double gy
    cdef double ar
    cdef double ag
    cdef double ab
    cdef double aa
    if leaf.member_op_count == 0:
        return
    px_start = <int>ceil(leaf.xmin + _half_w - 0.5)
    if px_start < 0:
        px_start = 0
    px_end = <int>floor(leaf.xmax + _half_w - 0.5)
    if px_end >= _buf_width:
        px_end = _buf_width - 1
    if px_start > px_end:
        return
    py_start = <int>ceil(leaf.ymin + _half_h - 0.5)
    if py_start < 0:
        py_start = 0
    py_end = <int>floor(leaf.ymax + _half_h - 0.5)
    if py_end >= _buf_height:
        py_end = _buf_height - 1
    if py_start > py_end:
        return
    for py in range(py_start, py_end + 1):
        gy = py + 0.5 - _half_h
        for px in range(px_start, px_end + 1):
            gx = px + 0.5 - _half_w
            _composite_leaf_pixel(gy, gx, leaf, &ar, &ag, &ab, &aa)
            write_rgba(px, py, clamp_u8(ar), clamp_u8(ag), clamp_u8(ab), clamp_u8(aa))


cdef void _render_quadtree_cells(int node_idx) except *:
    cdef CQuadNode node
    cdef int child_index
    if node_idx < 0 or node_idx >= _quad_node_count:
        return
    node = _quad_nodes[node_idx]
    if node.first_child >= 0:
        for child_index in range(4):
            _render_quadtree_cells(node.first_child + child_index)
        return
    _paint_leaf_cell(&node)


def render_quadtree() -> None:
    """Walk quadtree leaves and paint each cell's pixels in batch."""
    if _quad_node_count > 0:
        _render_quadtree_cells(0)


cdef int _op_slr_paint_pixel() except -1:
    """Stack gx -- . Legacy per-pixel path via quadtree point lookup."""
    cdef double gx = data_pop_float()
    cdef double gy = _current_gy
    cdef int px = <int>(gx + _half_w - 0.5)
    cdef int py = <int>(gy + _half_h - 0.5)
    cdef int leaf_idx
    cdef CQuadNode leaf
    cdef double ar
    cdef double ag
    cdef double ab
    cdef double aa
    if px < 0 or py < 0 or px >= _buf_width or py >= _buf_height:
        return 0
    leaf_idx = _leaf_index_at_point(gx, gy)
    if leaf_idx < 0:
        return 0
    leaf = _quad_nodes[leaf_idx]
    _composite_leaf_pixel(gy, gx, &leaf, &ar, &ag, &ab, &aa)
    write_rgba(px, py, clamp_u8(ar), clamp_u8(ag), clamp_u8(ab), clamp_u8(aa))
    return 0


slr_set_gy = _handler(_op_slr_set_gy)
slr_dup_xy = _handler(_op_slr_dup_xy)
slr_dup_anchor_push_xy = _handler(_op_slr_dup_anchor_push_xy)
slr_float_max2 = _handler(_op_slr_float_max2)
slr_float_neg = _handler(_op_slr_float_neg)
slr_offset_xy_sub = _handler(_op_slr_offset_xy_sub)
slr_rgba_solid_if_hit = _handler(_op_slr_rgba_solid_if_hit)
slr_circle_distance = _handler(_op_slr_circle_distance)
slr_rectangle_distance = _handler(_op_slr_rectangle_distance)
slr_oval_distance = _handler(_op_slr_oval_distance)
slr_fill_white = _handler(_op_slr_fill_white)
slr_rgba_transparent = _handler(_op_slr_rgba_transparent)
slr_push_transparent_accum = _handler(_op_slr_push_transparent_accum)
slr_dup_anchor_xy = _handler(_op_slr_dup_anchor_xy)
slr_drop_hit_xy = _handler(_op_slr_drop_hit_xy)
slr_anchorize_rgba = _handler(_op_slr_anchorize_rgba)
slr_src_over_layer = _handler(_op_slr_src_over_layer)
slr_continue_if_not_opaque = _handler(_op_slr_continue_if_not_opaque)
slr_sdf_fill_white = _handler(_op_slr_sdf_fill_white)
slr_python_distance = _handler(_op_slr_python_distance)
slr_python_color_at = _handler(_op_slr_python_color_at)
slr_paint_pixel = _handler(_op_slr_paint_pixel)
