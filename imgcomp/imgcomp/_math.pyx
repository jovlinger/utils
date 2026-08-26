# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True

"""Local typed math for imgcomp: SDF distances, src-over, pixel writes."""

from libc.math cimport fabs, hypot as c_hypot


cdef inline int clamp_channel(double value) noexcept nogil:
    if value <= 0.0:
        return 0
    if value >= 255.0:
        return 255
    return <int>(value + 0.5)


cdef inline double c_max(double a, double b) noexcept nogil:
    return a if a > b else b


cdef inline double c_min(double a, double b) noexcept nogil:
    return a if a < b else b


def circle_distance(double x, double y, double radius) -> float:
    """Signed distance to a disk centered at the origin."""
    return c_hypot(x, y) - radius


def rectangle_distance(
    double x,
    double y,
    double half_width,
    double half_height,
) -> float:
    """Signed distance to an axis-aligned rectangle centered at the origin."""
    cdef double qx = fabs(x) - half_width
    cdef double qy = fabs(y) - half_height
    cdef double outside = c_hypot(c_max(qx, 0.0), c_max(qy, 0.0))
    cdef double inside = c_min(c_max(qx, qy), 0.0)
    return outside + inside


def oval_distance(
    double x,
    double y,
    double radius_x,
    double radius_y,
) -> float:
    """Approximate signed distance to an axis-aligned ellipse at the origin."""
    cdef double nx = x / radius_x
    cdef double ny = y / radius_y
    cdef double scale = c_min(radius_x, radius_y)
    return (c_hypot(nx, ny) - 1.0) * scale


def src_over(
    int dr,
    int dg,
    int db,
    int da,
    int sr,
    int sg,
    int sb,
    int sa,
) -> tuple:
    """Composite src over dst (matches imgcomp.rgba.src_over argument order)."""
    cdef double src_a
    cdef double dst_a
    cdef double out_a
    cdef double inv_out

    if sa <= 0:
        return dr, dg, db, da
    if sa >= 255:
        return sr, sg, sb, sa
    src_a = sa / 255.0
    dst_a = da / 255.0
    out_a = src_a + dst_a * (1.0 - src_a)
    if out_a <= 0.0:
        return 0, 0, 0, 0
    inv_out = 1.0 / out_a
    return (
        clamp_channel((sr * src_a + dr * dst_a * (1.0 - src_a)) * inv_out),
        clamp_channel((sg * src_a + dg * dst_a * (1.0 - src_a)) * inv_out),
        clamp_channel((sb * src_a + db * dst_a * (1.0 - src_a)) * inv_out),
        clamp_channel(out_a * 255.0),
    )


def set_pixel_rgba(
    unsigned char[:] buffer,
    int offset,
    int red,
    int green,
    int blue,
    int alpha,
) -> None:
    """Write four RGBA bytes at ``offset`` into a byte buffer."""
    buffer[offset] = red
    buffer[offset + 1] = green
    buffer[offset + 2] = blue
    buffer[offset + 3] = alpha
