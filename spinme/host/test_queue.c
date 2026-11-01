/* Host test: MP/SC queue peek/handle/pop; full drop; shape lock is distinct. */
#include "ta_event.h"
#include "ta_queue.h"

#include <pthread.h>
#include <stdio.h>
#include <string.h>

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

static ta_event_t storage[4];
static ta_queue_t q;
static int handled;

static void *consumer(void *arg) {
    ta_event_t ev;
    int n = 0;

    (void)arg;
    while (n < 3) {
        ta_queue_peek_wait(&q, &ev);
        /* Handler runs without holding push discipline beyond peek snapshot. */
        CHECK(ev.session_id == 7);
        handled++;
        ta_queue_pop(&q);
        n++;
    }
    return NULL;
}

int main(void) {
    pthread_t th;
    ta_event_t ev;
    ta_shape_lock_t shapes;
    int i;

    CHECK(ta_queue_init(&q, storage, 4) == 0);
    CHECK(ta_shape_lock_init(&shapes) == 0);
    /* Prove shape lock type is usable and separate from queue. */
    ta_shape_lock_acquire(&shapes);
    ta_shape_lock_release(&shapes);

    CHECK(pthread_create(&th, NULL, consumer, NULL) == 0);

    for (i = 0; i < 3; i++) {
        ta_event_clear(&ev);
        ta_event_set_src(&ev, "Prod");
        ev.session_id = 7;
        ev.type = (ta_event_type_t)(10 + i);
        CHECK(ta_queue_push(&q, &ev) == 0);
    }

    pthread_join(th, NULL);
    CHECK(handled == 3);

    /* Fill then one drop. */
    for (i = 0; i < 4; i++) {
        ta_event_clear(&ev);
        ta_event_set_src(&ev, "Prod");
        ev.session_id = 1;
        CHECK(ta_queue_push(&q, &ev) == 0);
    }
    CHECK(ta_queue_push(&q, &ev) == -1);
    CHECK(q.drops == 1);

    ta_shape_lock_fini(&shapes);
    ta_queue_fini(&q);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_queue: %d checks ok\n", checks);
    return 0;
}
