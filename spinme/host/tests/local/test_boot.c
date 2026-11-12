/* Boot walks KV roster, stub-loads each actor blob, calls init. */
#include "ta_boot.h"
#include "ta_kv.h"
#include "ta_registry.h"

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
    ta_registry_reset();
    ta_kv_install_factory();
    CHECK(ta_boot_from_kv() == 2);
    CHECK(ta_boot_running_count() == 2);
    CHECK(ta_registry_lookup("Draw") != NULL);
    CHECK(ta_registry_lookup("Net") != NULL);
    ta_boot_exit_all();
    CHECK(ta_boot_running_count() == 0);
    CHECK(ta_registry_lookup("Draw") == NULL);
    CHECK(ta_registry_lookup("Net") == NULL);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_boot: %d checks ok\n", checks);
    return 0;
}
