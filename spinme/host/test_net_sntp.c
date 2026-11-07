/* Host: Net SNTP seam records after_wifi. */
#include "ta_net_sntp.h"

#include <stdio.h>

static int failures;
static int checks;

#define CHECK(cond)                                                            \
    do {                                                                       \
        checks++;                                                              \
        if (!(cond)) {                                                         \
            failures++;                                                        \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__,   \
                    #cond);                                                    \
        }                                                                      \
    } while (0)

int main(void) {
    ta_net_sntp_reset();
    CHECK(ta_net_sntp_started() == 0);
    ta_net_sntp_after_wifi();
    CHECK(ta_net_sntp_started() == 1);
    ta_net_sntp_reset();
    CHECK(ta_net_sntp_started() == 0);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_net_sntp: %d checks ok\n", checks);
    return 0;
}
