#include "ta_syslog_host.h"

#include "ta_log_accept.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netdb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

static int parse_url(const char *url, int *udp, char *host, size_t host_cap,
                     char *port, size_t port_cap) {
    const char *p;
    const char *colon;
    size_t hlen;

    if (url == NULL || host == NULL || port == NULL || host_cap < 2 ||
        port_cap < 2) {
        return -1;
    }
    *udp = 1;
    p = url;
    if (strncmp(p, "udp://", 6) == 0) {
        *udp = 1;
        p += 6;
    } else if (strncmp(p, "tcp://", 6) == 0) {
        *udp = 0;
        p += 6;
    } else if (strncmp(p, "syslog://", 9) == 0) {
        *udp = 1;
        p += 9;
    } else {
        return -1;
    }
    colon = strrchr(p, ':');
    if (colon == NULL || colon == p) {
        snprintf(port, port_cap, "514");
        hlen = strlen(p);
    } else {
        hlen = (size_t)(colon - p);
        snprintf(port, port_cap, "%s", colon + 1);
    }
    if (hlen == 0 || hlen >= host_cap) {
        return -1;
    }
    memcpy(host, p, hlen);
    host[hlen] = '\0';
    return 0;
}

int ta_syslog_send_bytes(const char *url, const void *data, size_t n) {
    char host[128];
    char port[16];
    int udp;
    struct addrinfo hints;
    struct addrinfo *res = NULL;
    struct addrinfo *rp;
    int fd = -1;
    int rc = -1;
    int socktype;

    if (data == NULL || n == 0) {
        return 0;
    }
    if (parse_url(url, &udp, host, sizeof(host), port, sizeof(port)) != 0) {
        return -1;
    }
    socktype = udp ? SOCK_DGRAM : SOCK_STREAM;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = socktype;
    if (getaddrinfo(host, port, &hints, &res) != 0) {
        return -1;
    }
    for (rp = res; rp != NULL; rp = rp->ai_next) {
        fd = socket(rp->ai_family, rp->ai_socktype, rp->ai_protocol);
        if (fd < 0) {
            continue;
        }
        if (udp) {
            if (sendto(fd, data, n, 0, rp->ai_addr, rp->ai_addrlen) ==
                (ssize_t)n) {
                rc = 0;
            }
            close(fd);
            fd = -1;
            if (rc == 0) {
                break;
            }
        } else {
            if (connect(fd, rp->ai_addr, rp->ai_addrlen) == 0) {
                if (write(fd, data, n) == (ssize_t)n) {
                    rc = 0;
                }
                close(fd);
                fd = -1;
                break;
            }
            close(fd);
            fd = -1;
        }
    }
    freeaddrinfo(res);
    (void)errno;
    return rc;
}

int ta_syslog_log_send(const char *url, const ta_log_accept_event_t *rows,
                       size_t n, void *ud) {
    size_t i;
    int any_ok = 0;

    (void)ud;
    if (url == NULL || url[0] == '\0' || rows == NULL) {
        return -1;
    }
    for (i = 0; i < n; i++) {
        char line[256];
        size_t ln;

        ln = ta_log_format_syslog(line, sizeof(line), rows[i].emit_time_ms,
                                  rows[i].message);
        if (ln == 0) {
            continue;
        }
        if (ln + 1 < sizeof(line)) {
            line[ln++] = '\n';
            line[ln] = '\0';
        }
        if (ta_syslog_send_bytes(url, line, ln) == 0) {
            any_ok = 1;
        }
    }
    return any_ok ? 0 : -1;
}

void ta_syslog_install_default_sender(void) {
    ta_log_set_sender(ta_syslog_log_send, NULL);
}
