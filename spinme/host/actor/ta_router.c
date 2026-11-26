#include "ta_router.h"

#include "ta_net_events.h"
#include "ta_net_http_event.h"
#include "ta_registry.h"

#include <stdio.h>
#include <string.h>

#define TA_DEBUG_AGG_MAX 512
#define TA_DEBUG_NAME_SLOTS 32

static char g_target[TA_NAME_MAX];

/* In-flight DebugAll collection (HTTP session). */
static int g_dbg_active;
static ta_session_id_t g_dbg_sid;
static unsigned g_dbg_expected;
static unsigned g_dbg_got;
static char g_dbg_body[TA_DEBUG_AGG_MAX];
static size_t g_dbg_len;

void ta_router_reset(void) {
    g_target[0] = '\0';
    g_dbg_active = 0;
    g_dbg_sid = 0;
    g_dbg_expected = 0;
    g_dbg_got = 0;
    g_dbg_body[0] = '\0';
    g_dbg_len = 0;
}

const char *ta_router_current_target(void) {
    return g_target;
}

static int set_route(const ta_event_envelope_t *env) {
    const char *name = env->event.u.ctrl_set_route.target;

    if (name[0] == '\0') {
        fprintf(stderr, "ERROR: SetRoute bad target\n");
        return -1;
    }
    memcpy(g_target, name, TA_NAME_MAX);
    return 0;
}

static void dbg_offer_if_complete(void) {
    ta_event_envelope_t reply;

    if (!g_dbg_active) {
        return;
    }
    if (g_dbg_got < g_dbg_expected) {
        return;
    }
    if (g_dbg_len > 0) {
        ta_net_http_offer_blob(g_dbg_sid, 200u, g_dbg_body, g_dbg_len);
    } else {
        ta_env_clear(&reply);
        reply.session_id = g_dbg_sid;
        reply.event.type = TA_EV_NET_HTTP_REPLY;
        reply.event.u.net_http_reply.http_status = 200;
        reply.event.u.net_http_reply.n = 0;
        ta_net_http_offer_reply(&reply);
    }
    g_dbg_active = 0;
}

static int append_dbg_line(const char *src, const char *text) {
    int n;
    size_t room;

    if (src == NULL || src[0] == '\0') {
        src = "?";
    }
    if (text == NULL) {
        text = "";
    }
    room = sizeof(g_dbg_body) - g_dbg_len;
    if (room < 4) {
        return -1;
    }
    n = snprintf(g_dbg_body + g_dbg_len, room, "%s=%s\n", src, text);
    if (n < 0 || (size_t)n >= room) {
        g_dbg_body[sizeof(g_dbg_body) - 1] = '\0';
        g_dbg_len = sizeof(g_dbg_body) - 1;
        return -1;
    }
    g_dbg_len += (size_t)n;
    return 0;
}

static int handle_debug_status_reply(const ta_event_envelope_t *env) {
    if (!g_dbg_active || env->session_id != g_dbg_sid) {
        return 0;
    }
    (void)append_dbg_line(env->src, env->event.u.debug_status.text);
    g_dbg_got++;
    dbg_offer_if_complete();
    return 0;
}

static int handle_debug_all(const ta_event_envelope_t *env) {
    char names[TA_DEBUG_NAME_SLOTS][TA_NAME_MAX];
    size_t n;
    size_t i;
    ta_event_envelope_t req;

    g_dbg_active = 1;
    g_dbg_sid = env->session_id;
    g_dbg_expected = 0;
    g_dbg_got = 0;
    g_dbg_body[0] = '\0';
    g_dbg_len = 0;

    n = ta_registry_copy_names(&names[0][0], TA_NAME_MAX, TA_DEBUG_NAME_SLOTS);
    /* Count first so sync replies during post cannot complete early. */
    for (i = 0; i < n; i++) {
        if (strcmp(names[i], "controller") != 0) {
            g_dbg_expected++;
        }
    }
    for (i = 0; i < n; i++) {
        if (strcmp(names[i], "controller") == 0) {
            continue;
        }
        ta_env_clear(&req);
        (void)ta_env_set_src(&req, "controller");
        req.session_id = env->session_id;
        req.event.type = TA_EV_DEBUG_STATUS;
        req.event.u.debug_status.text[0] = '\0';
        (void)ta_registry_post(names[i], &req);
    }
    /* Zero actors: still a complete empty aggregate. */
    dbg_offer_if_complete();
    /* Incomplete: leave HTTP wait open; Net TIMEOUT_SHORT -> 201. */
    return 0;
}

static int handle_list_tasks(const ta_event_envelope_t *env) {
    char names[TA_DEBUG_NAME_SLOTS][TA_NAME_MAX];
    char body[TA_DEBUG_NAME_SLOTS * TA_NAME_MAX];
    size_t n;
    size_t i;
    size_t o;

    n = ta_registry_copy_names(&names[0][0], TA_NAME_MAX, TA_DEBUG_NAME_SLOTS);
    o = 0;
    body[0] = '\0';
    for (i = 0; i < n; i++) {
        int wrote;

        if (names[i][0] == '\0') {
            continue;
        }
        wrote = snprintf(body + o, sizeof(body) - o, "%s\n", names[i]);
        if (wrote < 0 || (size_t)wrote >= sizeof(body) - o) {
            break;
        }
        o += (size_t)wrote;
    }
    return ta_list_events_offer(env, body[0] != '\0' ? body : "\n");
}

int ta_router_enqueue(const ta_event_envelope_t *env) {
    if (env == NULL) {
        return -1;
    }
    if (env->event.type == TA_EV_SET_ROUTE) {
        return set_route(env);
    }
    if (env->event.type == TA_EV_DEBUG_ALL) {
        return handle_debug_all(env);
    }
    if (env->event.type == TA_EV_LIST_TASKS) {
        return handle_list_tasks(env);
    }
    if (env->event.type == TA_EV_LIST_EVENTS) {
        return ta_list_events_offer(
            env,
            "list_events,list_tasks,debugall,debug_status,ctrlsetroute");
    }
    if (env->event.type == TA_EV_DEBUG_STATUS) {
        /* Actor replies: src is not Controller (requests use src=Controller). */
        if (strcmp(env->src, "controller") != 0) {
            return handle_debug_status_reply(env);
        }
        return 0;
    }
    if (g_target[0] == '\0') {
        fprintf(stderr, "ERROR: Controller has no route\n");
        return -1;
    }
    /* Forward envelope intact (typed body + session_id). */
    return ta_registry_post(g_target, env);
}

void ta_router_start(void) {
    (void)ta_registry_register(TA_CONTROLLER_NAME, ta_router_enqueue);
}
