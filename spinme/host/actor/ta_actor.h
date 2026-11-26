/* Loadable TaskActor entry points: init() and exit() are inverses.
 * init registers the name and runs the event loop until exit().
 * On host the loop is a thread so tests can call exit from outside.
 */
#ifndef SPINME_TA_ACTOR_H
#define SPINME_TA_ACTOR_H

#include "ta_event.h"

#include <pthread.h>

typedef struct ta_actor {
    char name[TA_NAME_MAX];
    volatile int running;
    volatile int entered;
    int thread_ok;
    pthread_t thread;
} ta_actor_t;

/* Register name, set running, start the loop. 0 on success. */
int ta_actor_init(ta_actor_t *actor, const char *name);
/* Stop the loop, join it, unregister. Inverse of init. */
void ta_actor_exit(ta_actor_t *actor);

#endif
