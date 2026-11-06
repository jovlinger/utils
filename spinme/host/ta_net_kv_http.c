#include "ta_net_kv_http.h"

#include <string.h>

static int is_key_char(unsigned char c) {
    return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
           (c >= '0' && c <= '9') || c == '_' || c == '-';
}

ta_kv_status_t ta_net_kv_http_set(const uint8_t *req, size_t len) {
    const char *text;
    const char *line_end;
    const char *key;
    const char *key_end;
    const char *hdr_end;
    const char *cl;
    char keybuf[TA_KV_KEY_MAX];
    size_t klen;
    size_t body_len;
    size_t i;
    const uint8_t *body;

    if (req == NULL || len < 16) {
        return TA_KV_BAD_ARG;
    }
    text = (const char *)req;
    line_end = NULL;
    for (i = 0; i + 1 < len; i++) {
        if (req[i] == '\r' && req[i + 1] == '\n') {
            line_end = text + i;
            break;
        }
    }
    if (line_end == NULL) {
        return TA_KV_BAD_ARG;
    }
    if (strncmp(text, "PUT /kv/", 8) != 0) {
        return TA_KV_BAD_ARG;
    }
    key = text + 8;
    key_end = key;
    while (key_end < line_end && is_key_char((unsigned char)*key_end)) {
        key_end++;
    }
    klen = (size_t)(key_end - key);
    if (klen == 0 || klen >= TA_KV_KEY_MAX) {
        return TA_KV_BAD_ARG;
    }
    if (key_end >= line_end || *key_end != ' ') {
        return TA_KV_BAD_ARG;
    }
    memcpy(keybuf, key, klen);
    keybuf[klen] = '\0';

    hdr_end = NULL;
    for (i = 0; i + 3 < len; i++) {
        if (req[i] == '\r' && req[i + 1] == '\n' && req[i + 2] == '\r' &&
            req[i + 3] == '\n') {
            hdr_end = text + i + 4;
            break;
        }
    }
    if (hdr_end == NULL) {
        return TA_KV_BAD_ARG;
    }
    cl = NULL;
    for (i = (size_t)(line_end - text); i + 16 < (size_t)(hdr_end - text); i++) {
        if (strncmp(text + i, "Content-Length:", 15) == 0) {
            cl = text + i + 15;
            break;
        }
    }
    if (cl == NULL) {
        return TA_KV_BAD_ARG;
    }
    while (cl < hdr_end && *cl == ' ') {
        cl++;
    }
    body_len = 0;
    if (cl >= hdr_end || *cl < '0' || *cl > '9') {
        return TA_KV_BAD_ARG;
    }
    while (cl < hdr_end && *cl >= '0' && *cl <= '9') {
        body_len = body_len * 10u + (size_t)(*cl - '0');
        cl++;
    }
    body = (const uint8_t *)hdr_end;
    if ((size_t)(body - req) + body_len > len) {
        return TA_KV_BAD_ARG;
    }
    return ta_kv_put(keybuf, body, body_len);
}
