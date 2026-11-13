#include "ta_actor.h"

#include "ta_net_http_event.h"
#include "ta_registry.h"

#include <sched.h>
#include <string.h>

static int actor_enqueue(const ta_event_envelope_t *env) {
    if (env != NULL && env->event.type == TA_EV_LIST_EVENTS) {
        return ta_list_events_offer(env, "list_events");
    }
    return 0;
}

static void *actor_loop(void *arg) {
    ta_actor_t *actor;

    actor = (ta_actor_t *)arg;
    actor->entered = 1;
    while (actor->running) {
        (void)sched_yield();
    }
    return NULL;
}

int ta_actor_init(ta_actor_t *actor, const char *name) {
    size_t n;

    if (actor == NULL || name == NULL || name[0] == '\0') {
        return -1;
    }
    n = strlen(name);
    if (n >= TA_NAME_MAX) {
        return -1;
    }
    memset(actor, 0, sizeof(*actor));
    memcpy(actor->name, name, n + 1);
    if (ta_registry_register(name, actor_enqueue) != 0) {
        return -1;
    }
    actor->running = 1;
    if (pthread_create(&actor->thread, NULL, actor_loop, actor) != 0) {
        actor->running = 0;
        (void)ta_registry_unregister(name);
        return -1;
    }
    actor->thread_ok = 1;
    return 0;
}

void ta_actor_exit(ta_actor_t *actor) {
    if (actor == NULL) {
        return;
    }
    actor->running = 0;
    if (actor->thread_ok) {
        (void)pthread_join(actor->thread, NULL);
        actor->thread_ok = 0;
    }
    (void)ta_registry_unregister(actor->name);
}
