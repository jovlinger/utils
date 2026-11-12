/* PC: fork/exec build/test_*. Device: built-in probes (smoke). HTTP offers reply. */
#include "ta_test_actor.h"

#include "ta_net_events.h"
#include "ta_net_http_event.h"
#include "ta_registry.h"

#include <stdio.h>
#include <string.h>
#include <time.h>

#ifndef SPINME_TA_DEVICE
#include <sys/wait.h>
#include <unistd.h>
#endif

static ta_test_stats_t g_stats;

typedef struct {
    const char *name;
    const char *const *members;
} ta_test_suite_t;

/* Short names map to ./build/test_<name>. Suites expand to member lists. */
static const char *const k_suite_smoke[] = {"smoke", NULL};
static const char *const k_suite_event[] = {
    "event_envelope", "draw_events", "net_events", "sched_events",
    "sched_cadence", "net_http_event", NULL};
static const char *const k_suite_base[] = {
    "queue", "isr_mail", "kv", "runtime_cfg", NULL};
static const char *const k_suite_actor[] = {
    "registry_logger", "router", "actor", "boot", "controller", "all_init",
    "kv_actor", "log_accept", "log_drain", "log_init", "input_isr",
    "net_mpd", "net_kv_http", "net_sntp", "mpd_net", "test_actor", NULL};
static const char *const k_suite_shape[] = {
    "uilayout", "shape_l2r", "text", "draw_update", "draw_phase1",
    "draw_phase2", "follow_chrome", "hit_dispatch", "viewport", "artwork",
    "shape_swap", "kv_editor", "wire", "under_image", "draw_glass_contract",
    "draw_glass_owner", "debug", "shape_draw", NULL};
static const char *const k_suite_ui[] = {
    "screenshots", "xy_timed_redraw", NULL};
static const char *const k_suite_all[] = {
    "smoke",
    "event_envelope",
    "queue",
    "registry_logger",
    "router",
    "isr_mail",
    "kv",
    "runtime_cfg",
    "draw_events",
    "net_events",
    "sched_events",
    "sched_cadence",
    "follow_chrome",
    "hit_dispatch",
    "net_mpd",
    "viewport",
    "artwork",
    "controller",
    "mpd_net",
    "draw_glass_contract",
    "under_image",
    "input_isr",
    "uilayout",
    "shape_l2r",
    "text",
    "draw_update",
    "draw_phase1",
    "draw_phase2",
    "actor",
    "boot",
    "net_kv_http",
    "net_http_event",
    "all_init",
    "kv_actor",
    "log_accept",
    "log_drain",
    "log_init",
    "net_sntp",
    "shape_swap",
    "kv_editor",
    "wire",
    "debug",
    "screenshots",
    "draw_glass_owner",
    "xy_timed_redraw",
    "shape_draw",
    "test_actor",
    NULL};

static const ta_test_suite_t k_suites[] = {
    {"smoke", k_suite_smoke},
    {"event", k_suite_event},
    {"base", k_suite_base},
    {"actor", k_suite_actor},
    {"shape", k_suite_shape},
    {"ui", k_suite_ui},
    {"all", k_suite_all},
};

void ta_test_reset(void) {
    memset(&g_stats, 0, sizeof(g_stats));
}

const ta_test_stats_t *ta_test_stats(void) {
    return &g_stats;
}

static uint32_t mono_ms(void) {
    struct timespec ts;

    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        return 0;
    }
    return (uint32_t)(ts.tv_sec * 1000u + (uint32_t)(ts.tv_nsec / 1000000u));
}

static void offer_http_reply(ta_session_id_t session, uint8_t status,
                             uint16_t n_ran, uint16_t n_fail,
                             uint32_t elapsed_ms, const char *selector) {
    ta_event_envelope_t reply;
    char body[TA_NET_HTTP_RESP_BODY_MAX];
    int n;

    ta_env_clear(&reply);
    (void)ta_env_set_src(&reply, TA_TEST_NAME);
    reply.session_id = session;
    reply.event.type = TA_EV_NET_HTTP_REPLY;
    reply.event.u.net_http_reply.http_status = (status == 0) ? 200u : 500u;
    n = snprintf(body, sizeof(body),
                 "status=%u&n_ran=%u&n_fail=%u&elapsed_ms=%u&selector=%s",
                 (unsigned)status, (unsigned)n_ran, (unsigned)n_fail,
                 (unsigned)elapsed_ms, selector != NULL ? selector : "");
    if (n < 0) {
        n = 0;
    }
    if ((size_t)n >= sizeof(body)) {
        n = (int)sizeof(body) - 1;
    }
    if ((size_t)n > TA_NET_HTTP_REPLY_MAX) {
        n = (int)TA_NET_HTTP_REPLY_MAX;
    }
    reply.event.u.net_http_reply.n = (uint16_t)n;
    memcpy(reply.event.u.net_http_reply.bytes, body, (size_t)n);
    ta_net_http_offer_reply(&reply);
}

static void post_done(const char *reply_to, ta_session_id_t session,
                      uint8_t status, uint16_t n_ran, uint16_t n_fail,
                      uint32_t elapsed_ms, const char *selector) {
    ta_event_envelope_t reply;

    offer_http_reply(session, status, n_ran, n_fail, elapsed_ms, selector);

    if (reply_to == NULL || reply_to[0] == '\0') {
        g_stats.dones++;
        return;
    }
    ta_env_clear(&reply);
    (void)ta_env_set_src(&reply, TA_TEST_NAME);
    reply.session_id = session;
    reply.event.type = TA_EV_TEST_DONE;
    reply.event.u.test_done.status = status;
    reply.event.u.test_done.n_ran = n_ran;
    reply.event.u.test_done.n_fail = n_fail;
    reply.event.u.test_done.elapsed_ms = elapsed_ms;
    (void)ta_copy_name(reply.event.u.test_done.selector, TA_TEST_SEL_MAX,
                       selector != NULL ? selector : "");
    if (ta_registry_post(reply_to, &reply) == 0) {
        g_stats.dones++;
    }
}

#ifndef SPINME_TA_DEVICE
static int run_one_binary(const char *short_name) {
    char path[96];
    pid_t pid;
    int status;

    if (short_name == NULL || short_name[0] == '\0') {
        return -1;
    }
    if ((size_t)snprintf(path, sizeof(path), "./build/test_%s", short_name) >=
        sizeof(path)) {
        return -1;
    }
    pid = fork();
    if (pid < 0) {
        return -1;
    }
    if (pid == 0) {
        execl(path, path, (char *)NULL);
        _exit(127);
    }
    if (waitpid(pid, &status, 0) < 0) {
        return -1;
    }
    if (WIFEXITED(status) && WEXITSTATUS(status) == 0) {
        return 0;
    }
    return -1;
}
#else
/* On device: only built-in probes (no fork). Expand as board checks land. */
static int run_one_binary(const char *short_name) {
    if (short_name != NULL && strcmp(short_name, "smoke") == 0) {
        return 0;
    }
    return -1;
}
#endif

static const char *const *suite_members(const char *name) {
    size_t i;

    if (name == NULL) {
        return NULL;
    }
    for (i = 0; i < sizeof(k_suites) / sizeof(k_suites[0]); i++) {
        if (strcmp(k_suites[i].name, name) == 0) {
            return k_suites[i].members;
        }
    }
    return NULL;
}

static int run_list(const char *const *names, uint16_t *n_ran, uint16_t *n_fail) {
    size_t i;

    *n_ran = 0;
    *n_fail = 0;
    if (names == NULL) {
        return -1;
    }
    for (i = 0; names[i] != NULL; i++) {
        (*n_ran)++;
        if (run_one_binary(names[i]) != 0) {
            (*n_fail)++;
        }
    }
    return (*n_fail == 0) ? 0 : -1;
}

int ta_test_handle(const ta_event_envelope_t *env) {
    const ta_test_run_t *run;
    const char *const *members;
    const char *one[2];
    uint16_t n_ran;
    uint16_t n_fail;
    uint32_t t0;
    uint32_t elapsed;
    int rc;
    uint8_t mode;

    if (env == NULL) {
        return -1;
    }
    g_stats.handled++;
    if (env->event.type != TA_EV_TEST_RUN) {
        g_stats.unknown++;
        return -1;
    }
    run = &env->event.u.test_run;
    mode = run->mode;
    g_stats.runs++;
    t0 = mono_ms();
    n_ran = 0;
    n_fail = 0;
    rc = -1;

    if (mode == TA_TEST_MODE_SUITE) {
        members = suite_members(run->selector);
        rc = run_list(members, &n_ran, &n_fail);
    } else if (mode == TA_TEST_MODE_ONE || mode == TA_TEST_MODE_TIMING) {
        /* Timing is one binary with elapsed_ms filled on DONE. */
        one[0] = run->selector;
        one[1] = NULL;
        rc = run_list(one, &n_ran, &n_fail);
    } else {
        g_stats.unknown++;
        post_done(run->reply_to, env->session_id, 1, 0, 0, 0, run->selector);
        return -1;
    }

    elapsed = mono_ms() - t0;
    post_done(run->reply_to, env->session_id, (uint8_t)(rc == 0 ? 0 : 1), n_ran,
              n_fail, elapsed, run->selector);
    return rc;
}

int ta_test_enqueue(const ta_event_envelope_t *env) {
    return ta_test_handle(env);
}

void ta_test_start(void) {
    ta_test_reset();
    (void)ta_registry_register(TA_TEST_NAME, ta_test_enqueue);
}

int ta_test_post_run(uint8_t mode, const char *selector, const char *reply_to,
                     ta_session_id_t session) {
    ta_event_envelope_t env;

    if (selector == NULL || selector[0] == '\0') {
        return -1;
    }
    ta_env_clear(&env);
    if (ta_env_set_src(&env, "Caller") != 0) {
        return -1;
    }
    env.session_id = session;
    env.event.type = TA_EV_TEST_RUN;
    env.event.u.test_run.mode = mode;
    if (ta_copy_name(env.event.u.test_run.selector, TA_TEST_SEL_MAX, selector) !=
        0) {
        return -1;
    }
    if (reply_to != NULL && reply_to[0] != '\0') {
        if (ta_copy_name(env.event.u.test_run.reply_to, TA_NAME_MAX, reply_to) !=
            0) {
            return -1;
        }
    }
    return ta_registry_post(TA_TEST_NAME, &env);
}
