# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True
"""Test-only Python entry points for ``imgcomp._math`` cdef affine kernels."""

from cpython.mem cimport PyMem_Free, PyMem_Malloc

from imgcomp._math cimport (
    Affine2,
    affine_mat_mul,
    affine_mat_vec_batch,
    affine_mat_vec_xy,
    affine_set,
)

cdef extern from "affine_simd.h":
    const char *imgcomp_affine_simd_backend()


cdef Affine2 _bench_general_matrix() noexcept nogil:
    cdef Affine2 m
    m.a = 1.02
    m.b = -0.15
    m.c = 0.08
    m.d = 0.97
    m.tx = 3.5
    m.ty = -2.25
    return m


cdef Affine2 _bench_left_matrix() noexcept nogil:
    cdef Affine2 m
    m.a = 1.001
    m.b = -0.02
    m.c = 0.03
    m.d = 0.999
    m.tx = 0.5
    m.ty = -0.25
    return m


cdef Affine2 _bench_right_matrix() noexcept nogil:
    cdef Affine2 m
    m.a = 0.98
    m.b = 0.11
    m.c = -0.07
    m.d = 1.03
    m.tx = -1.25
    m.ty = 0.75
    return m


def simd_backend() -> str:
    return imgcomp_affine_simd_backend().decode("ascii")


def bench_mat_mul(int steps) -> tuple:
    cdef int i
    cdef Affine2 left = _bench_left_matrix()
    cdef Affine2 right = _bench_right_matrix()
    cdef Affine2 out
    cdef double checksum = 0.0
    cdef object timer = __import__("time", None, None, None)
    cdef double t0 = timer.perf_counter()
    for i in range(steps):
        affine_mat_mul(&out, &left, &right)
        checksum += out.a + out.d + out.tx - out.ty
    return checksum, timer.perf_counter() - t0


def bench_mat_vec_xy(int steps) -> tuple:
    cdef int i
    cdef Affine2 m = _bench_general_matrix()
    cdef double ox = 0.0
    cdef double oy = 0.0
    cdef double checksum = 0.0
    cdef object timer = __import__("time", None, None, None)
    cdef double t0 = timer.perf_counter()
    for i in range(steps):
        affine_mat_vec_xy(&ox, &oy, &m, 1.25, -0.75)
        checksum += ox + oy
    return checksum, timer.perf_counter() - t0


def bench_mat_vec_batch(double[:] in_x, double[:] in_y, int repeat) -> tuple:
    cdef Py_ssize_t n = in_x.shape[0]
    cdef Affine2 m = _bench_general_matrix()
    cdef double* out_x_ptr = <double*>PyMem_Malloc(n * sizeof(double))
    cdef double* out_y_ptr = <double*>PyMem_Malloc(n * sizeof(double))
    cdef Py_ssize_t i
    cdef int r
    cdef double checksum = 0.0
    cdef object timer = __import__("time", None, None, None)
    cdef double t0
    if out_x_ptr == NULL or out_y_ptr == NULL:
        if out_x_ptr != NULL:
            PyMem_Free(out_x_ptr)
        if out_y_ptr != NULL:
            PyMem_Free(out_y_ptr)
        raise MemoryError()
    try:
        t0 = timer.perf_counter()
        for r in range(repeat):
            affine_mat_vec_batch(
                out_x_ptr,
                out_y_ptr,
                &in_x[0],
                &in_y[0],
                &m,
                n,
            )
        for i in range(n):
            checksum += out_x_ptr[i] + out_y_ptr[i]
        return checksum, timer.perf_counter() - t0
    finally:
        PyMem_Free(out_x_ptr)
        PyMem_Free(out_y_ptr)


def compose_chain(int steps) -> tuple:
    cdef int i
    cdef Affine2 stretch
    cdef Affine2 rot
    cdef Affine2 translate
    cdef Affine2 acc
    cdef Affine2 tmp
    from imgcomp.affine import Affine

    rot_key = Affine.rotate(0.7).as_key()
    affine_set(&stretch, 1.001, 0.0, 0.0, 0.999, 0.0, 0.0)
    affine_set(&rot, rot_key[0], rot_key[1], rot_key[2], rot_key[3], rot_key[4], rot_key[5])
    affine_set(&translate, 1.0, 0.0, 0.0, 1.0, 0.5, -0.25)
    affine_set(&acc, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for i in range(steps):
        affine_mat_mul(&tmp, &stretch, &rot)
        affine_mat_mul(&acc, &translate, &tmp)
    return acc.a, acc.b, acc.c, acc.d, acc.tx, acc.ty


def transform_batch(
    double[:] in_x,
    double[:] in_y,
    double a,
    double b,
    double c,
    double d,
    double tx,
    double ty,
) -> tuple:
    cdef Py_ssize_t n = in_x.shape[0]
    cdef Py_ssize_t i
    cdef Affine2 m
    cdef double* out_x_ptr = <double*>PyMem_Malloc(n * sizeof(double))
    cdef double* out_y_ptr = <double*>PyMem_Malloc(n * sizeof(double))
    cdef list xs
    cdef list ys
    if out_x_ptr == NULL or out_y_ptr == NULL:
        if out_x_ptr != NULL:
            PyMem_Free(out_x_ptr)
        if out_y_ptr != NULL:
            PyMem_Free(out_y_ptr)
        raise MemoryError()
    try:
        affine_set(&m, a, b, c, d, tx, ty)
        affine_mat_vec_batch(
            out_x_ptr,
            out_y_ptr,
            &in_x[0],
            &in_y[0],
            &m,
            n,
        )
        xs = [0.0] * n
        ys = [0.0] * n
        for i in range(n):
            xs[i] = out_x_ptr[i]
            ys[i] = out_y_ptr[i]
        return xs, ys
    finally:
        PyMem_Free(out_x_ptr)
        PyMem_Free(out_y_ptr)
