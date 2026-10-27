/* Host integration: mocked player, virtual clock, A-side posts.
 *
 * Three expected ERROR lines on stderr, from the overflow section:
 *   event ring full, dropped volume
 *   event ring full, dropped update_render_draw
 *   event ring full, dropped clock
 *
 * The timed path is a separate binary. From this directory:
 *   make integ-bench
 */
#include "integ_script.h"

#include <stdio.h>
#include <stdlib.h>

int main(void) {
    int checks = 0;
    int failures = integ_script_run(&checks);
    printf("test_integ: %d checks, %d failures\n", checks, failures);
    return failures != 0 ? EXIT_FAILURE : EXIT_SUCCESS;
}
