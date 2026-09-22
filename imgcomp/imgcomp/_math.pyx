# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True
"""C-level 2D affine kernels for imgcomp (matXmat / matXvec / batch matXvec).

``Affine2`` stores ``[a b tx; c d ty]``. All hot paths are ``cdef`` + ``nogil``.

Optimization notes (apply when calling from other Cython, not via Python ``def``):

- **matXmat** (``affine_mat_mul``): peephole identity / translate / scale+translate
  and single-sided translate compose; general path hoists ``left``/``right`` coeffs
  to locals with ``restrict`` (safe in-place only when ``out`` does not alias inputs).
- **matXvec** (``affine_mat_vec_xy``): same peephole matrix classes; coeffs hoisted
  before the multiply.
- **batch matXvec** (``affine_mat_vec_batch``): peephole paths use ``memcpy`` or
  scalar loops; general path uses hoisted coeffs and a scalar loop for ``n < 16``,
  then ``affine_simd.c`` (NEON ``vfmaq`` / SSE2, 4-wide unroll) for larger ``n``.

Cython scalar loops here do not auto-vectorize; explicit SIMD lives in ``affine_simd.c``.
"""

from libc.math cimport fabs
from libc.stddef cimport size_t
from libc.string cimport memcpy

cdef double _AFFINE_EPS = 1e-12
cdef Py_ssize_t _AFFINE_SIMD_MIN = 16


cdef inline bint _near(double x, double y) noexcept nogil:
    return fabs(x - y) <= _AFFINE_EPS


cdef inline void vec2_set(Vec2 *restrict v, double x, double y) noexcept nogil:
    v.x = x
    v.y = y


cdef inline void affine_set(
    Affine2 *restrict m,
    double a,
    double b,
    double c,
    double d,
    double tx,
    double ty,
) noexcept nogil:
    m.a = a
    m.b = b
    m.c = c
    m.d = d
    m.tx = tx
    m.ty = ty


cdef inline void affine_identity(Affine2 *restrict m) noexcept nogil:
    m.a = 1.0
    m.b = 0.0
    m.c = 0.0
    m.d = 1.0
    m.tx = 0.0
    m.ty = 0.0


cdef inline bint affine_is_identity(const Affine2 *restrict m) noexcept nogil:
    return (
        _near(m.a, 1.0)
        and _near(m.b, 0.0)
        and _near(m.c, 0.0)
        and _near(m.d, 1.0)
        and _near(m.tx, 0.0)
        and _near(m.ty, 0.0)
    )


cdef inline bint affine_is_translate(const Affine2 *restrict m) noexcept nogil:
    return (
        _near(m.a, 1.0)
        and _near(m.b, 0.0)
        and _near(m.c, 0.0)
        and _near(m.d, 1.0)
    )


cdef inline bint affine_is_scale_translate(const Affine2 *restrict m) noexcept nogil:
    return _near(m.b, 0.0) and _near(m.c, 0.0)


cdef inline void affine_mat_mul(
    Affine2 *restrict out,
    const Affine2 *restrict left,
    const Affine2 *restrict right,
) noexcept nogil:
    """Compose affines: ``out = left @ right`` (child ``right`` applied first)."""
    cdef double la
    cdef double lb
    cdef double lc
    cdef double ld
    cdef double ltx
    cdef double lty
    cdef double ra
    cdef double rb
    cdef double rc
    cdef double rd
    cdef double rtx
    cdef double rty
    if affine_is_identity(right):
        out[0] = left[0]
        return
    if affine_is_identity(left):
        out[0] = right[0]
        return
    if affine_is_translate(left) and affine_is_translate(right):
        out.a = 1.0
        out.b = 0.0
        out.c = 0.0
        out.d = 1.0
        out.tx = left.tx + right.tx
        out.ty = left.ty + right.ty
        return
    if affine_is_translate(left):
        out.a = right.a
        out.b = right.b
        out.c = right.c
        out.d = right.d
        out.tx = right.tx + left.tx
        out.ty = right.ty + left.ty
        return
    if affine_is_translate(right):
        la = left.a
        lb = left.b
        lc = left.c
        ld = left.d
        ltx = left.tx
        lty = left.ty
        rtx = right.tx
        rty = right.ty
        out.a = la
        out.b = lb
        out.c = lc
        out.d = ld
        out.tx = la * rtx + lb * rty + ltx
        out.ty = lc * rtx + ld * rty + lty
        return
    if affine_is_scale_translate(left) and affine_is_scale_translate(right):
        la = left.a
        ld = left.d
        ltx = left.tx
        lty = left.ty
        ra = right.a
        rd = right.d
        rtx = right.tx
        rty = right.ty
        out.a = la * ra
        out.b = 0.0
        out.c = 0.0
        out.d = ld * rd
        out.tx = la * rtx + ltx
        out.ty = ld * rty + lty
        return

    la = left.a
    lb = left.b
    lc = left.c
    ld = left.d
    ltx = left.tx
    lty = left.ty
    ra = right.a
    rb = right.b
    rc = right.c
    rd = right.d
    rtx = right.tx
    rty = right.ty
    out.a = la * ra + lb * rc
    out.b = la * rb + lb * rd
    out.c = lc * ra + ld * rc
    out.d = lc * rb + ld * rd
    out.tx = la * rtx + lb * rty + ltx
    out.ty = lc * rtx + ld * rty + lty


cdef extern from "affine_simd.h":
    void imgcomp_affine_batch_transform(
        double *restrict out_x,
        double *restrict out_y,
        const double *restrict in_x,
        const double *restrict in_y,
        const double *restrict m6,
        size_t n,
    ) noexcept nogil


cdef inline void _affine_batch_linear(
    double *restrict out_x,
    double *restrict out_y,
    const double *restrict in_x,
    const double *restrict in_y,
    double ma,
    double mb,
    double mc,
    double md,
    Py_ssize_t n,
) noexcept nogil:
    cdef Py_ssize_t i
    for i in range(n):
        out_x[i] = ma * in_x[i] + mb * in_y[i]
        out_y[i] = mc * in_x[i] + md * in_y[i]


cdef inline void _affine_batch_scalar(
    double *restrict out_x,
    double *restrict out_y,
    const double *restrict in_x,
    const double *restrict in_y,
    double ma,
    double mb,
    double mc,
    double md,
    double mtx,
    double mty,
    Py_ssize_t n,
) noexcept nogil:
    cdef Py_ssize_t i
    cdef double x
    cdef double y
    for i in range(n):
        x = in_x[i]
        y = in_y[i]
        out_x[i] = ma * x + mb * y + mtx
        out_y[i] = mc * x + md * y + mty


cdef void _affine_batch_general(
    double *restrict out_x,
    double *restrict out_y,
    const double *restrict in_x,
    const double *restrict in_y,
    const Affine2 *restrict m,
    Py_ssize_t n,
) noexcept nogil:
    cdef double ma = m.a
    cdef double mb = m.b
    cdef double mc = m.c
    cdef double md = m.d
    cdef double mtx = m.tx
    cdef double mty = m.ty
    cdef double m6[6]
    if _near(mtx, 0.0) and _near(mty, 0.0):
        _affine_batch_linear(out_x, out_y, in_x, in_y, ma, mb, mc, md, n)
        return
    if n < _AFFINE_SIMD_MIN:
        _affine_batch_scalar(out_x, out_y, in_x, in_y, ma, mb, mc, md, mtx, mty, n)
        return
    m6[0] = ma
    m6[1] = mb
    m6[2] = mc
    m6[3] = md
    m6[4] = mtx
    m6[5] = mty
    imgcomp_affine_batch_transform(out_x, out_y, in_x, in_y, m6, <size_t>n)


cdef inline void affine_mat_vec(
    Vec2 *restrict out,
    const Affine2 *restrict m,
    const Vec2 *restrict v,
) noexcept nogil:
    affine_mat_vec_xy(&out.x, &out.y, m, v.x, v.y)


cdef inline void affine_mat_vec_xy(
    double *restrict out_x,
    double *restrict out_y,
    const Affine2 *restrict m,
    double x,
    double y,
) noexcept nogil:
    """matXvec: ``out = m @ [x, y, 1]``."""
    cdef double ma
    cdef double mb
    cdef double mc
    cdef double md
    cdef double mtx
    cdef double mty
    if affine_is_identity(m):
        out_x[0] = x
        out_y[0] = y
        return
    if affine_is_translate(m):
        out_x[0] = x + m.tx
        out_y[0] = y + m.ty
        return
    if affine_is_scale_translate(m):
        out_x[0] = m.a * x + m.tx
        out_y[0] = m.d * y + m.ty
        return
    ma = m.a
    mb = m.b
    mc = m.c
    md = m.d
    mtx = m.tx
    mty = m.ty
    if _near(mtx, 0.0) and _near(mty, 0.0):
        out_x[0] = ma * x + mb * y
        out_y[0] = mc * x + md * y
        return
    out_x[0] = ma * x + mb * y + mtx
    out_y[0] = mc * x + md * y + mty


cdef void affine_mat_vec_batch(
    double *restrict out_x,
    double *restrict out_y,
    const double *restrict in_x,
    const double *restrict in_y,
    const Affine2 *restrict m,
    Py_ssize_t n,
) noexcept nogil:
    """Parallel matXvec: peepholes, scalar small-n, SIMD large-n."""
    cdef Py_ssize_t nbytes
    cdef double ma
    cdef double md
    cdef double mtx
    cdef double mty
    if n <= 0:
        return
    if affine_is_identity(m):
        nbytes = <Py_ssize_t>n * sizeof(double)
        memcpy(out_x, in_x, <size_t>nbytes)
        memcpy(out_y, in_y, <size_t>nbytes)
        return
    if affine_is_translate(m):
        mtx = m.tx
        mty = m.ty
        _affine_batch_scalar(out_x, out_y, in_x, in_y, 1.0, 0.0, 0.0, 1.0, mtx, mty, n)
        return
    if affine_is_scale_translate(m):
        ma = m.a
        md = m.d
        mtx = m.tx
        mty = m.ty
        _affine_batch_scalar(out_x, out_y, in_x, in_y, ma, 0.0, 0.0, md, mtx, mty, n)
        return
    _affine_batch_general(out_x, out_y, in_x, in_y, m, n)
