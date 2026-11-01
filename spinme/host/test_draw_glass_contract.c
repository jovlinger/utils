/*
 * RED end-test: Draw glass contract (PLAN).
 *
 * Literate expectations for update / phase1 / phase2 / under-image.
 * This binary is expected to FAIL until UILayout/Shape/Draw paint land.
 * `make test` treats exit!=0 as success for this one target.
 *
 * Contract (must become true):
 * 1) update: Shape defs + dirty only; pixmap bytes unchanged.
 * 2) phase1: farthest->nearest rebuild of dirty local pixmaps; under-image
 *    present so scroll/clock ticks do not recompose static chrome.
 * 3) phase2: whole dirty exteriors; coverage cull; clear dirty only after
 *    glass push; no full-frame shadow compare.
 * 4) under-image: base dirty rebuilds under; scroll/clock without box move
 *    does not dirty the under-Cache.
 */
#include <stdio.h>
#include <stdlib.h>

/* Intentionally no Draw paint API yet -- force a hard fail. */
int main(void) {
    fprintf(stderr,
            "RED test_draw_glass_contract: Draw glass API not implemented yet\n"
            "  missing: uilayout_update / draw_phase1_pixmaps / "
            "draw_phase2_coverage / under_image_invalidate\n"
            "  leave failing until WorkItems 0006..001e land\n");
    return 1;
}
