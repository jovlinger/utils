# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: initializedcheck=False
# cython: nonecheck=False
# cython: cdivision=True
"""C kernels and VM op handlers for simpletest circle rendering."""

from libc.stdint cimport int64_t

from imgcomp._stack_c cimport (
    OpHandler,
    _handler,
    data_pop_int,
    data_push_int,
)


cdef unsigned char[:] _pixels = None
cdef int _buf_width = 0
cdef int _buf_height = 0
cdef double _radius_sq = 0.0
cdef double _half_w = 0.0
cdef double _half_h = 0.0


def bind_surface(pixels, int width, int height, double radius) -> None:
    """Attach an RGBA byte buffer and viewport geometry for stacklang painting."""
    cdef unsigned char[:] view = pixels
    if view.shape[0] != width * height * 4:
        raise ValueError("pixel buffer size mismatch")
    global _pixels, _buf_width, _buf_height, _radius_sq, _half_w, _half_h
    _pixels = view
    _buf_width = width
    _buf_height = height
    _radius_sq = radius * radius
    _half_w = width / 2.0
    _half_h = height / 2.0


cdef inline void write_white(int px, int py) noexcept:
    cdef int offset = (py * _buf_width + px) * 4
    _pixels[offset] = 255
    _pixels[offset + 1] = 255
    _pixels[offset + 2] = 255
    _pixels[offset + 3] = 255


cdef int _op_circle_paint_at() except -1:
    """Stack: py px -- py . Paint one pixel; leave row index for the next column."""
    cdef int px = data_pop_int()
    cdef int py = data_pop_int()
    cdef double gx = px + 0.5 - _half_w
    cdef double gy = py + 0.5 - _half_h
    if gx * gx + gy * gy <= _radius_sq:
        write_white(px, py)
    data_push_int(py)


circle_paint_at = _handler(_op_circle_paint_at)


def render_circle_native(int width, int height, double radius) -> bytes:
    """Fill a transparent RGBA buffer with a centered white circle in C."""
    cdef bytearray buf = bytearray(width * height * 4)
    cdef unsigned char[:] pixels = buf
    cdef int px
    cdef int py
    cdef double half_w = width / 2.0
    cdef double half_h = height / 2.0
    cdef double radius_sq = radius * radius
    cdef double gx
    cdef double gy
    cdef int offset
    for py in range(height):
        gy = py + 0.5 - half_h
        for px in range(width):
            gx = px + 0.5 - half_w
            if gx * gx + gy * gy <= radius_sq:
                offset = (py * width + px) * 4
                pixels[offset] = 255
                pixels[offset + 1] = 255
                pixels[offset + 2] = 255
                pixels[offset + 3] = 255
    return bytes(buf)


def white_pixel_count(bytes rgba, int width, int height) -> int64_t:
    """Count pixels with alpha 255 (used to compare render paths)."""
    cdef const unsigned char[:] pixels = rgba
    cdef int64_t total = 0
    cdef int index = 3
    cdef int limit = width * height * 4
    while index < limit:
        if pixels[index] == 255:
            total += 1
        index += 4
    return total
