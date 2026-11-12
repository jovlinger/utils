#include "ta_net_http_event.h"

#include "ta_net_events.h"
#include "ta_registry.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TA_NET_HTTP_FORM_MAX 16
#define TA_NET_HTTP_KEY_MAX 32
#define TA_NET_HTTP_VAL_MAX 96

typedef struct {
    char key[TA_NET_HTTP_KEY_MAX];
    char val[TA_NET_HTTP_VAL_MAX];
} ta_net_http_kv_t;

static ta_net_http_wait_fn g_wait;
static ta_session_id_t g_sid_gen = 1;
static ta_session_id_t g_want_sid;
static ta_event_envelope_t g_offered;
static int g_have_offer;
static uint8_t *g_blob;
static size_t g_blob_len;
static unsigned g_blob_status;
static ta_session_id_t g_blob_sid;
static int g_have_blob;

static char g_mdns_name[TA_NAME_MAX];
static unsigned g_mdns_count;

static void clear_blob(void) {
    free(g_blob);
    g_blob = NULL;
    g_blob_len = 0;
    g_blob_status = 0;
    g_blob_sid = 0;
    g_have_blob = 0;
}

void ta_net_http_reset(void) {
    g_wait = NULL;
    g_want_sid = 0;
    g_have_offer = 0;
    memset(&g_offered, 0, sizeof(g_offered));
    clear_blob();
}

void ta_net_http_set_wait(ta_net_http_wait_fn fn) {
    g_wait = fn;
}

void ta_net_http_offer_reply(const ta_event_envelope_t *env) {
    if (env == NULL) {
        return;
    }
    if (env->event.type != TA_EV_NET_HTTP_REPLY) {
        return;
    }
    if (g_want_sid != 0 && env->session_id != g_want_sid) {
        return;
    }
    clear_blob();
    g_offered = *env;
    g_have_offer = 1;
}

void ta_net_http_offer_blob(ta_session_id_t session_id, unsigned http_status,
                            const void *bytes, size_t n) {
    uint8_t *copy;

    if (g_want_sid != 0 && session_id != g_want_sid) {
        return;
    }
    if (bytes == NULL || n == 0 || n > TA_NET_HTTP_BLOB_MAX) {
        return;
    }
    copy = (uint8_t *)malloc(n);
    if (copy == NULL) {
        return;
    }
    memcpy(copy, bytes, n);
    clear_blob();
    g_have_offer = 0;
    g_blob = copy;
    g_blob_len = n;
    g_blob_status = http_status;
    g_blob_sid = session_id;
    g_have_blob = 1;
}

static int default_wait(ta_session_id_t session_id, ta_event_envelope_t *out,
                        uint32_t timeout_ms) {
    (void)timeout_ms;
    if (g_have_blob && g_blob_sid == session_id) {
        if (out != NULL) {
            ta_env_clear(out);
            out->session_id = session_id;
            out->event.type = TA_EV_NET_HTTP_REPLY;
            out->event.u.net_http_reply.http_status = (uint16_t)g_blob_status;
            out->event.u.net_http_reply.n = 0;
        }
        return 0;
    }
    if (!g_have_offer || g_offered.session_id != session_id) {
        return -1;
    }
    if (out != NULL) {
        *out = g_offered;
    }
    g_have_offer = 0;
    return 0;
}

static int hex_nibble(char c) {
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    if (c >= 'A' && c <= 'F') {
        return c - 'A' + 10;
    }
    if (c >= 'a' && c <= 'f') {
        return c - 'a' + 10;
    }
    return -1;
}

static size_t url_decode(char *dst, size_t cap, const char *src, size_t n) {
    size_t di;
    size_t si;

    di = 0;
    si = 0;
    while (si < n && di + 1 < cap) {
        if (src[si] == '+' ) {
            dst[di++] = ' ';
            si++;
        } else if (src[si] == '%' && si + 2 < n) {
            int hi;
            int lo;

            hi = hex_nibble(src[si + 1]);
            lo = hex_nibble(src[si + 2]);
            if (hi < 0 || lo < 0) {
                dst[di++] = src[si++];
            } else {
                dst[di++] = (char)((hi << 4) | lo);
                si += 3;
            }
        } else {
            dst[di++] = src[si++];
        }
    }
    dst[di] = '\0';
    return di;
}

static int form_set(ta_net_http_kv_t *flat, size_t *nflat, const char *key,
                    const char *val) {
    size_t i;

    for (i = 0; i < *nflat; i++) {
        if (strcmp(flat[i].key, key) == 0) {
            snprintf(flat[i].val, sizeof(flat[i].val), "%s", val);
            return 0;
        }
    }
    if (*nflat >= TA_NET_HTTP_FORM_MAX) {
        return -1;
    }
    snprintf(flat[*nflat].key, sizeof(flat[*nflat].key), "%s", key);
    snprintf(flat[*nflat].val, sizeof(flat[*nflat].val), "%s", val);
    (*nflat)++;
    return 0;
}

static int parse_form(ta_net_http_kv_t *flat, size_t *nflat, const char *s,
                      size_t n) {
    size_t i;
    size_t start;

    i = 0;
    while (i < n) {
        const char *amp;
        const char *eq;
        char key[TA_NET_HTTP_KEY_MAX];
        char val[TA_NET_HTTP_VAL_MAX];
        size_t pair_n;
        size_t kn;
        size_t vn;

        start = i;
        while (i < n && s[i] != '&') {
            i++;
        }
        pair_n = i - start;
        if (i < n && s[i] == '&') {
            i++;
        }
        if (pair_n == 0) {
            continue;
        }
        eq = NULL;
        for (amp = s + start; amp < s + start + pair_n; amp++) {
            if (*amp == '=') {
                eq = amp;
                break;
            }
        }
        if (eq == NULL) {
            url_decode(key, sizeof(key), s + start, pair_n);
            val[0] = '\0';
        } else {
            kn = (size_t)(eq - (s + start));
            vn = pair_n - kn - 1;
            url_decode(key, sizeof(key), s + start, kn);
            url_decode(val, sizeof(val), eq + 1, vn);
        }
        if (key[0] == '\0') {
            continue;
        }
        if (form_set(flat, nflat, key, val) != 0) {
            return -1;
        }
    }
    return 0;
}

static void ascii_downcase(char *s) {
    size_t i;

    if (s == NULL) {
        return;
    }
    for (i = 0; s[i] != '\0'; i++) {
        if (s[i] >= 'A' && s[i] <= 'Z') {
            s[i] = (char)(s[i] - 'A' + 'a');
        }
    }
}

static const char *form_get(const ta_net_http_kv_t *flat, size_t nflat,
                            const char *key) {
    size_t i;

    for (i = 0; i < nflat; i++) {
        if (strcmp(flat[i].key, key) == 0) {
            return flat[i].val;
        }
    }
    return NULL;
}

static int build_event_from_form(const char *event_name,
                                 const ta_net_http_kv_t *flat, size_t nflat,
                                 ta_event_t *ev) {
    const char *v;

    ta_event_clear(ev);
    /* event_name is already ASCII-lowercased by the HTTP path parser. */
    if (strcmp(event_name, "logemitline") == 0) {
        ev->type = TA_EV_LOG;
        v = form_get(flat, nflat, "severity");
        ev->u.log_emit_line.severity = (uint8_t)(v ? atoi(v) : 0);
        v = form_get(flat, nflat, "tag");
        ev->u.log_emit_line.tag = (uint8_t)(v ? atoi(v) : 0);
        v = form_get(flat, nflat, "text");
        if (v == NULL) {
            v = "";
        }
        snprintf(ev->u.log_emit_line.text, sizeof(ev->u.log_emit_line.text),
                 "%s", v);
        return 0;
    }
    if (strcmp(event_name, "nop") == 0) {
        ev->type = TA_EV_NOP;
        return 0;
    }
    /* TestRun + run_test alias (path lowercased). */
    if (strcmp(event_name, "testrun") == 0 ||
        strcmp(event_name, "run_test") == 0) {
        ev->type = TA_EV_TEST_RUN;
        v = form_get(flat, nflat, "mode");
        if (v != NULL && strcmp(v, "suite") == 0) {
            ev->u.test_run.mode = TA_TEST_MODE_SUITE;
        } else if (v != NULL && strcmp(v, "timing") == 0) {
            ev->u.test_run.mode = TA_TEST_MODE_TIMING;
        } else if (v != NULL && (v[0] >= '0' && v[0] <= '9')) {
            ev->u.test_run.mode = (uint8_t)atoi(v);
        } else {
            ev->u.test_run.mode = TA_TEST_MODE_ONE;
        }
        v = form_get(flat, nflat, "selector");
        if (v == NULL) {
            v = form_get(flat, nflat, "name");
        }
        if (v == NULL) {
            v = "smoke";
        }
        snprintf(ev->u.test_run.selector, sizeof(ev->u.test_run.selector), "%s",
                 v);
        v = form_get(flat, nflat, "reply_to");
        if (v != NULL) {
            snprintf(ev->u.test_run.reply_to, sizeof(ev->u.test_run.reply_to),
                     "%s", v);
        } else {
            ev->u.test_run.reply_to[0] = '\0';
        }
        return 0;
    }
    if (strcmp(event_name, "get_debug") == 0) {
        ev->type = TA_EV_TEST_GET_DEBUG;
        return 0;
    }
    return -1;
}

static void fill_response(ta_net_http_response_t *out, int status,
                          const void *body, size_t body_len) {
    out->http_status = status;
    out->body_len = 0;
    out->body[0] = '\0';
    free(out->blob);
    out->blob = NULL;
    out->blob_len = 0;
    if (body != NULL && body_len > 0) {
        if (body_len >= sizeof(out->body)) {
            body_len = sizeof(out->body) - 1;
        }
        memcpy(out->body, body, body_len);
        out->body[body_len] = '\0';
        out->body_len = body_len;
    }
}

static void fill_response_blob(ta_net_http_response_t *out, int status,
                               uint8_t *blob, size_t blob_len) {
    size_t prefix;

    out->http_status = status;
    free(out->blob);
    out->blob = blob;
    out->blob_len = blob_len;
    prefix = blob_len;
    if (prefix >= sizeof(out->body)) {
        prefix = sizeof(out->body) - 1;
    }
    if (blob != NULL && prefix > 0) {
        memcpy(out->body, blob, prefix);
    }
    out->body[prefix] = '\0';
    out->body_len = prefix;
}

int ta_net_http_handle_request(const uint8_t *req, size_t len,
                               ta_net_http_response_t *out) {
    const char *text;
    const char *line_end;
    const char *hdr_end;
    const char *path;
    const char *qmark;
    const char *sp;
    char actor[TA_NAME_MAX];
    char event_name[48];
    ta_net_http_kv_t flat[TA_NET_HTTP_FORM_MAX];
    size_t nflat;
    size_t i;
    size_t body_len;
    const char *body;
    ta_event_envelope_t env;
    ta_event_envelope_t reply;
    ta_session_id_t sid;
    ta_net_http_wait_fn waitfn;
    int rc;

    if (req == NULL || out == NULL || len < 16) {
        return -1;
    }
    text = (const char *)req;
    line_end = NULL;
    for (i = 0; i + 1 < len; i++) {
        if (req[i] == '\r' && req[i + 1] == '\n') {
            line_end = text + i;
            break;
        }
    }
    if (line_end == NULL || strncmp(text, "POST /event/", 12) != 0) {
        fill_response(out, 400, "bad request", 11);
        return 0;
    }
    path = text + 12;
    sp = path;
    while (sp < line_end && *sp != ' ') {
        sp++;
    }
    if (sp >= line_end) {
        fill_response(out, 400, "bad request", 11);
        return 0;
    }
    {
        const char *slash;
        size_t alen;
        size_t elen;

        slash = NULL;
        for (i = 0; path + i < sp; i++) {
            if (path[i] == '/') {
                slash = path + i;
                break;
            }
        }
        if (slash == NULL) {
            fill_response(out, 400, "bad path", 8);
            return 0;
        }
        alen = (size_t)(slash - path);
        if (alen == 0 || alen >= sizeof(actor)) {
            fill_response(out, 400, "bad actor", 9);
            return 0;
        }
        memcpy(actor, path, alen);
        actor[alen] = '\0';
        ascii_downcase(actor);
        qmark = NULL;
        for (i = 0; slash + 1 + i < sp; i++) {
            if (slash[1 + i] == '?') {
                qmark = slash + 1 + i;
                break;
            }
        }
        if (qmark == NULL) {
            elen = (size_t)(sp - (slash + 1));
        } else {
            elen = (size_t)(qmark - (slash + 1));
        }
        if (elen == 0 || elen >= sizeof(event_name)) {
            fill_response(out, 400, "bad event", 9);
            return 0;
        }
        memcpy(event_name, slash + 1, elen);
        event_name[elen] = '\0';
        ascii_downcase(event_name);
    }

    hdr_end = NULL;
    for (i = 0; i + 3 < len; i++) {
        if (req[i] == '\r' && req[i + 1] == '\n' && req[i + 2] == '\r' &&
            req[i + 3] == '\n') {
            hdr_end = text + i + 4;
            break;
        }
    }
    if (hdr_end == NULL) {
        fill_response(out, 400, "bad headers", 11);
        return 0;
    }

    nflat = 0;
    if (qmark != NULL && qmark + 1 < sp) {
        if (parse_form(flat, &nflat, qmark + 1, (size_t)(sp - (qmark + 1))) !=
            0) {
            fill_response(out, 400, "bad query", 9);
            return 0;
        }
    }

    body_len = 0;
    body = hdr_end;
    {
        const char *cl;
        size_t hdr_span;

        cl = NULL;
        hdr_span = (size_t)(hdr_end - text);
        for (i = 0; i + 15 < hdr_span; i++) {
            if (strncmp(text + i, "Content-Length:", 15) == 0) {
                cl = text + i + 15;
                break;
            }
        }
        if (cl != NULL) {
            while (cl < hdr_end && *cl == ' ') {
                cl++;
            }
            while (cl < hdr_end && *cl >= '0' && *cl <= '9') {
                body_len = body_len * 10u + (size_t)(*cl - '0');
                cl++;
            }
            if ((size_t)(body - (const char *)req) + body_len > len) {
                fill_response(out, 400, "short body", 10);
                return 0;
            }
            if (body_len > 0) {
                if (parse_form(flat, &nflat, body, body_len) != 0) {
                    fill_response(out, 400, "bad body", 8);
                    return 0;
                }
            }
        }
    }

    if (ta_registry_lookup(actor) == NULL) {
        fill_response(out, 404, "actor not found", 15);
        return 0;
    }

    ta_env_clear(&env);
    (void)ta_env_set_src(&env, "Net");
    sid = g_sid_gen++;
    if (g_sid_gen == 0) {
        g_sid_gen = 1;
    }
    env.session_id = sid;
    if (build_event_from_form(event_name, flat, nflat, &env.event) != 0) {
        fill_response(out, 400, "unknown event", 13);
        return 0;
    }

    g_want_sid = sid;
    g_have_offer = 0;
    if (ta_registry_post(actor, &env) != 0) {
        g_want_sid = 0;
        fill_response(out, 500, "enqueue failed", 14);
        return 0;
    }

    waitfn = g_wait != NULL ? g_wait : default_wait;
    rc = waitfn(sid, &reply, TA_NET_HTTP_TIMEOUT_MS);
    g_want_sid = 0;
    if (g_have_blob && g_blob_sid == sid) {
        fill_response_blob(out, (int)g_blob_status, g_blob, g_blob_len);
        g_blob = NULL;
        g_blob_len = 0;
        g_have_blob = 0;
        return 0;
    }
    if (rc != 0) {
        fill_response(out, 201, "accepted", 8);
        return 0;
    }
    if (reply.event.type != TA_EV_NET_HTTP_REPLY) {
        fill_response(out, 502, "bad reply", 9);
        return 0;
    }
    fill_response(out, (int)reply.event.u.net_http_reply.http_status,
                  reply.event.u.net_http_reply.bytes,
                  (size_t)reply.event.u.net_http_reply.n);
    return 0;
}

void ta_net_mdns_reset(void) {
    g_mdns_count = 0;
    snprintf(g_mdns_name, sizeof(g_mdns_name), "%s", "spinme");
}

void ta_net_mdns_set_name(const char *name) {
    if (name == NULL || name[0] == '\0') {
        return;
    }
    snprintf(g_mdns_name, sizeof(g_mdns_name), "%s", name);
}

int ta_net_mdns_advertise(void) {
    /* Host stub: count broadcasts. Device will emit real mDNS. */
    (void)g_mdns_name;
    g_mdns_count++;
    return 0;
}

unsigned ta_net_mdns_advertise_count(void) {
    return g_mdns_count;
}
