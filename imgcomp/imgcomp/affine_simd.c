#include "affine_simd.h"

#include <stddef.h>

#if defined(__aarch64__) || defined(__ARM_NEON) || defined(__ARM_NEON__)
#define IMGCOMP_HAVE_NEON 1
#include <arm_neon.h>
#elif defined(__SSE2__) || defined(_M_X64) || defined(_M_AMD64)
#define IMGCOMP_HAVE_SSE2 1
#include <emmintrin.h>
#endif

const char *imgcomp_affine_simd_backend(void) {
#if defined(IMGCOMP_HAVE_NEON)
    return "neon";
#elif defined(IMGCOMP_HAVE_SSE2)
    return "sse2";
#else
    return "scalar";
#endif
}

static void batch_scalar(
    double *restrict out_x,
    double *restrict out_y,
    const double *restrict in_x,
    const double *restrict in_y,
    const double ma,
    const double mb,
    const double mc,
    const double md,
    const double mtx,
    const double mty,
    size_t n) {
    size_t i;
    for (i = 0; i < n; ++i) {
        const double x = in_x[i];
        const double y = in_y[i];
        out_x[i] = ma * x + mb * y + mtx;
        out_y[i] = mc * x + md * y + mty;
    }
}

#if defined(IMGCOMP_HAVE_NEON)

static void batch_simd(
    double *restrict out_x,
    double *restrict out_y,
    const double *restrict in_x,
    const double *restrict in_y,
    const double ma,
    const double mb,
    const double mc,
    const double md,
    const double mtx,
    const double mty,
    size_t n) {
    const float64x2_t va = vdupq_n_f64(ma);
    const float64x2_t vb = vdupq_n_f64(mb);
    const float64x2_t vc = vdupq_n_f64(mc);
    const float64x2_t vd = vdupq_n_f64(md);
    const float64x2_t vtx = vdupq_n_f64(mtx);
    const float64x2_t vty = vdupq_n_f64(mty);
    size_t i = 0;
    size_t limit = n - (n & 3U);
    while (i < limit) {
        const float64x2_t vx0 = vld1q_f64(in_x + i);
        const float64x2_t vy0 = vld1q_f64(in_y + i);
        const float64x2_t vx1 = vld1q_f64(in_x + i + 2);
        const float64x2_t vy1 = vld1q_f64(in_y + i + 2);
        float64x2_t ox0 = vfmaq_f64(vtx, va, vx0);
        float64x2_t oy0 = vfmaq_f64(vty, vc, vx0);
        float64x2_t ox1 = vfmaq_f64(vtx, va, vx1);
        float64x2_t oy1 = vfmaq_f64(vty, vc, vx1);
        ox0 = vfmaq_f64(ox0, vb, vy0);
        oy0 = vfmaq_f64(oy0, vd, vy0);
        ox1 = vfmaq_f64(ox1, vb, vy1);
        oy1 = vfmaq_f64(oy1, vd, vy1);
        vst1q_f64(out_x + i, ox0);
        vst1q_f64(out_y + i, oy0);
        vst1q_f64(out_x + i + 2, ox1);
        vst1q_f64(out_y + i + 2, oy1);
        i += 4;
    }
    for (; i < n; ++i) {
        const double x = in_x[i];
        const double y = in_y[i];
        out_x[i] = ma * x + mb * y + mtx;
        out_y[i] = mc * x + md * y + mty;
    }
}

#elif defined(IMGCOMP_HAVE_SSE2)

static void batch_simd(
    double *restrict out_x,
    double *restrict out_y,
    const double *restrict in_x,
    const double *restrict in_y,
    const double ma,
    const double mb,
    const double mc,
    const double md,
    const double mtx,
    const double mty,
    size_t n) {
    const __m128d va = _mm_set1_pd(ma);
    const __m128d vb = _mm_set1_pd(mb);
    const __m128d vc = _mm_set1_pd(mc);
    const __m128d vd = _mm_set1_pd(md);
    const __m128d vtx = _mm_set1_pd(mtx);
    const __m128d vty = _mm_set1_pd(mty);
    size_t i = 0;
    size_t limit = n - (n & 3U);
    while (i < limit) {
        const __m128d vx0 = _mm_loadu_pd(in_x + i);
        const __m128d vy0 = _mm_loadu_pd(in_y + i);
        const __m128d vx1 = _mm_loadu_pd(in_x + i + 2);
        const __m128d vy1 = _mm_loadu_pd(in_y + i + 2);
        __m128d ox0 = _mm_add_pd(_mm_add_pd(_mm_mul_pd(va, vx0), _mm_mul_pd(vb, vy0)), vtx);
        __m128d oy0 = _mm_add_pd(_mm_add_pd(_mm_mul_pd(vc, vx0), _mm_mul_pd(vd, vy0)), vty);
        __m128d ox1 = _mm_add_pd(_mm_add_pd(_mm_mul_pd(va, vx1), _mm_mul_pd(vb, vy1)), vtx);
        __m128d oy1 = _mm_add_pd(_mm_add_pd(_mm_mul_pd(vc, vx1), _mm_mul_pd(vd, vy1)), vty);
        _mm_storeu_pd(out_x + i, ox0);
        _mm_storeu_pd(out_y + i, oy0);
        _mm_storeu_pd(out_x + i + 2, ox1);
        _mm_storeu_pd(out_y + i + 2, oy1);
        i += 4;
    }
    for (; i < n; ++i) {
        const double x = in_x[i];
        const double y = in_y[i];
        out_x[i] = ma * x + mb * y + mtx;
        out_y[i] = mc * x + md * y + mty;
    }
}

#else

static void batch_simd(
    double *restrict out_x,
    double *restrict out_y,
    const double *restrict in_x,
    const double *restrict in_y,
    const double ma,
    const double mb,
    const double mc,
    const double md,
    const double mtx,
    const double mty,
    size_t n) {
    batch_scalar(out_x, out_y, in_x, in_y, ma, mb, mc, md, mtx, mty, n);
}

#endif

void imgcomp_affine_batch_transform(
    double *restrict out_x,
    double *restrict out_y,
    const double *restrict in_x,
    const double *restrict in_y,
    const double *restrict m6,
    size_t n) {
    const double ma = m6[0];
    const double mb = m6[1];
    const double mc = m6[2];
    const double md = m6[3];
    const double mtx = m6[4];
    const double mty = m6[5];
#if defined(IMGCOMP_HAVE_NEON) || defined(IMGCOMP_HAVE_SSE2)
    if (n < 16) {
        batch_scalar(out_x, out_y, in_x, in_y, ma, mb, mc, md, mtx, mty, n);
        return;
    }
    batch_simd(out_x, out_y, in_x, in_y, ma, mb, mc, md, mtx, mty, n);
#else
    batch_scalar(out_x, out_y, in_x, in_y, ma, mb, mc, md, mtx, mty, n);
#endif
}
