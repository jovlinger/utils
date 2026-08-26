# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True

"""Typed paint kernel for specialized (flattened) scenes -- PIC hit path."""

from libc.math cimport fabs

DEF KIND_INFINITE = 0
DEF KIND_CIRCLE = 1
DEF KIND_RECT = 2
DEF KIND_RING = 3


cdef inline int clamp_channel(double value) noexcept nogil:
    if value <= 0.0:
        return 0
    if value >= 255.0:
        return 255
    return <int>(value + 0.5)


cdef inline void src_over_python(
    unsigned char dst_r,
    unsigned char dst_g,
    unsigned char dst_b,
    unsigned char dst_a,
    unsigned char src_r,
    unsigned char src_g,
    unsigned char src_b,
    unsigned char src_a,
    unsigned char* out_r,
    unsigned char* out_g,
    unsigned char* out_b,
    unsigned char* out_a,
) noexcept nogil:
    """Match imgcomp.rgba.src_over(dst, src): composite src over dst."""
    if src_a <= 0:
        out_r[0] = dst_r
        out_g[0] = dst_g
        out_b[0] = dst_b
        out_a[0] = dst_a
        return
    if src_a >= 255:
        out_r[0] = src_r
        out_g[0] = src_g
        out_b[0] = src_b
        out_a[0] = src_a
        return
    cdef double src_a_f = src_a / 255.0
    cdef double dst_a_f = dst_a / 255.0
    cdef double out_a_f = src_a_f + dst_a_f * (1.0 - src_a_f)
    if out_a_f <= 0.0:
        out_r[0] = 0
        out_g[0] = 0
        out_b[0] = 0
        out_a[0] = 0
        return
    cdef double inv_out = 1.0 / out_a_f
    out_r[0] = clamp_channel((src_r * src_a_f + dst_r * dst_a_f * (1.0 - src_a_f)) * inv_out)
    out_g[0] = clamp_channel((src_g * src_a_f + dst_g * dst_a_f * (1.0 - src_a_f)) * inv_out)
    out_b[0] = clamp_channel((src_b * src_a_f + dst_b * dst_a_f * (1.0 - src_a_f)) * inv_out)
    out_a[0] = clamp_channel(out_a_f * 255.0)


cdef inline bint hit_circle(
    double x,
    double y,
    double cx,
    double cy,
    double radius,
) nogil:
    cdef double dx = x - cx
    cdef double dy = y - cy
    return dx * dx + dy * dy <= radius * radius


cdef inline bint hit_rect(
    double x,
    double y,
    double cx,
    double cy,
    double half_w,
    double half_h,
) nogil:
    return fabs(x - cx) <= half_w and fabs(y - cy) <= half_h


cdef inline bint hit_ring(
    double x,
    double y,
    double cx,
    double cy,
    double outer_r,
    double inner_r,
) nogil:
    cdef double dx = x - cx
    cdef double dy = y - cy
    cdef double dist2 = dx * dx + dy * dy
    return dist2 <= outer_r * outer_r and dist2 > inner_r * inner_r


cdef inline bint sprite_hit(
    int kind,
    double x,
    double y,
    double tx,
    double ty,
    double p0,
    double p1,
) nogil:
    if kind == KIND_INFINITE:
        return True
    if kind == KIND_CIRCLE:
        return hit_circle(x, y, tx, ty, p0)
    if kind == KIND_RECT:
        return hit_rect(x, y, tx, ty, p0, p1)
    if kind == KIND_RING:
        return hit_ring(x, y, tx, ty, p0, p1)
    return False


cdef void composite_layer(
    double x,
    double y,
    int start,
    int end,
    const unsigned char[:] kinds,
    const double[:] params,
    const unsigned char[:] colors,
    unsigned char* out_r,
    unsigned char* out_g,
    unsigned char* out_b,
    unsigned char* out_a,
) noexcept nogil:
    cdef int sprite_index
    cdef int kind
    cdef int param_index
    cdef int color_index
    cdef double tx
    cdef double ty
    cdef double p0
    cdef double p1
    cdef unsigned char sr
    cdef unsigned char sg
    cdef unsigned char sb
    cdef unsigned char sa
    cdef unsigned char layer_r = 0
    cdef unsigned char layer_g = 0
    cdef unsigned char layer_b = 0
    cdef unsigned char layer_a = 0

    for sprite_index in range(end - 1, start - 1, -1):
        kind = kinds[sprite_index]
        param_index = sprite_index * 4
        tx = params[param_index]
        ty = params[param_index + 1]
        p0 = params[param_index + 2]
        p1 = params[param_index + 3]
        if not sprite_hit(kind, x, y, tx, ty, p0, p1):
            continue
        color_index = sprite_index * 4
        sr = colors[color_index]
        sg = colors[color_index + 1]
        sb = colors[color_index + 2]
        sa = colors[color_index + 3]
        # Member as dst under existing layer accum as src (top of union).
        src_over_python(
            sr,
            sg,
            sb,
            sa,
            layer_r,
            layer_g,
            layer_b,
            layer_a,
            &layer_r,
            &layer_g,
            &layer_b,
            &layer_a,
        )
        if layer_a >= 255:
            break

    out_r[0] = layer_r
    out_g[0] = layer_g
    out_b[0] = layer_b
    out_a[0] = layer_a


cdef void accumulate_pixel(
    double x,
    double y,
    const unsigned char[:] kinds,
    const double[:] params,
    const unsigned char[:] colors,
    const int[:] layer_starts,
    const int[:] layer_ends,
    unsigned char* out_r,
    unsigned char* out_g,
    unsigned char* out_b,
    unsigned char* out_a,
) noexcept nogil:
    cdef int layer_index
    cdef int start
    cdef int end
    cdef unsigned char layer_r
    cdef unsigned char layer_g
    cdef unsigned char layer_b
    cdef unsigned char layer_a

    out_r[0] = 0
    out_g[0] = 0
    out_b[0] = 0
    out_a[0] = 0

    for layer_index in range(layer_ends.shape[0] - 1, -1, -1):
        start = layer_starts[layer_index]
        end = layer_ends[layer_index]
        composite_layer(
            x,
            y,
            start,
            end,
            kinds,
            params,
            colors,
            &layer_r,
            &layer_g,
            &layer_b,
            &layer_a,
        )
        if layer_a <= 0:
            continue
        # Layer color as dst under current accum as src (closer layers on top).
        src_over_python(
            layer_r,
            layer_g,
            layer_b,
            layer_a,
            out_r[0],
            out_g[0],
            out_b[0],
            out_a[0],
            out_r,
            out_g,
            out_b,
            out_a,
        )
        if out_a[0] >= 255:
            return


def rasterize_into(
    int width,
    int height,
    int x0,
    int y0,
    int x1,
    int y1,
    unsigned char[:] kinds,
    double[:] params,
    unsigned char[:] colors,
    int[:] layer_starts,
    int[:] layer_ends,
    unsigned char[:] buffer,
    bint tile_buffer=False,
) -> None:
    """Fill ``buffer`` for viewport pixels [x0, x1) x [y0, y1).

    When ``tile_buffer`` is True, ``buffer`` is only the sub-rect.
    """
    cdef double half_w = width / 2.0
    cdef double half_h = height / 2.0
    cdef int y
    cdef int x
    cdef double local_x
    cdef double local_y
    cdef int offset
    cdef int tile_w = x1 - x0
    cdef unsigned char out_r
    cdef unsigned char out_g
    cdef unsigned char out_b
    cdef unsigned char out_a

    if x0 < 0:
        x0 = 0
    if y0 < 0:
        y0 = 0
    if x1 > width:
        x1 = width
    if y1 > height:
        y1 = height

    for y in range(y0, y1):
        local_y = y + 0.5 - half_h
        for x in range(x0, x1):
            local_x = x + 0.5 - half_w
            accumulate_pixel(
                local_x,
                local_y,
                kinds,
                params,
                colors,
                layer_starts,
                layer_ends,
                &out_r,
                &out_g,
                &out_b,
                &out_a,
            )
            if tile_buffer:
                offset = ((y - y0) * tile_w + (x - x0)) * 4
            else:
                offset = (y * width + x) * 4
            buffer[offset] = out_r
            buffer[offset + 1] = out_g
            buffer[offset + 2] = out_b
            buffer[offset + 3] = out_a
