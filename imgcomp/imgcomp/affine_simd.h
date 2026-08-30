#ifndef IMGCOMP_AFFINE_SIMD_H
#define IMGCOMP_AFFINE_SIMD_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

const char *imgcomp_affine_simd_backend(void);

void imgcomp_affine_batch_transform(
    double *restrict out_x,
    double *restrict out_y,
    const double *restrict in_x,
    const double *restrict in_y,
    const double *restrict m6,
    size_t n);

#ifdef __cplusplus
}
#endif

#endif
