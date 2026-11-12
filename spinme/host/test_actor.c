/* Registers an actor on init and removes it on exit. */
#include "ta_actor.h"
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
    ta_actor_t actor;
    unsigned spins;

    ta_registry_reset();
    CHECK(ta_actor_init(&actor, "Draw") == 0);
    CHECK(ta_registry_lookup("Draw") != NULL);
    spins = 0;
    while (!actor.entered && spins < 1000000u) {
        spins++;
    }
    CHECK(actor.entered == 1);
    CHECK(actor.running == 1);
    ta_actor_exit(&actor);
    CHECK(actor.running == 0);
    CHECK(ta_registry_lookup("Draw") == NULL);
    CHECK(ta_registry_unregister("Draw") == -1);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_actor: %d checks ok\n", checks);
    return 0;
}
