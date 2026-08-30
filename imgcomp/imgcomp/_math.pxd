# Shared C-level 2D affine types for imgcomp extensions.

cdef struct Vec2:
    double x
    double y

cdef struct Affine2:
    double a
    double b
    double c
    double d
    double tx
    double ty

cdef void vec2_set(Vec2 *restrict v, double x, double y) noexcept nogil
cdef void affine_set(
    Affine2 *restrict m,
    double a,
    double b,
    double c,
    double d,
    double tx,
    double ty,
) noexcept nogil
cdef void affine_identity(Affine2 *restrict m) noexcept nogil
cdef bint affine_is_identity(const Affine2 *restrict m) noexcept nogil
cdef bint affine_is_translate(const Affine2 *restrict m) noexcept nogil
cdef bint affine_is_scale_translate(const Affine2 *restrict m) noexcept nogil
cdef void affine_mat_mul(
    Affine2 *restrict out,
    const Affine2 *restrict left,
    const Affine2 *restrict right,
) noexcept nogil
cdef void affine_mat_vec(
    Vec2 *restrict out,
    const Affine2 *restrict m,
    const Vec2 *restrict v,
) noexcept nogil
cdef void affine_mat_vec_xy(
    double *restrict out_x,
    double *restrict out_y,
    const Affine2 *restrict m,
    double x,
    double y,
) noexcept nogil
cdef void affine_mat_vec_batch(
    double *restrict out_x,
    double *restrict out_y,
    const double *restrict in_x,
    const double *restrict in_y,
    const Affine2 *restrict m,
    Py_ssize_t n,
) noexcept nogil
