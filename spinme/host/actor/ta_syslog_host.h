/* Host POSIX syslog send for QuLog (RFC 5424 over UDP/TCP). */
#ifndef SPINME_TA_SYSLOG_HOST_H
#define SPINME_TA_SYSLOG_HOST_H

#include "ta_log_accept.h"

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Parse udp://host:port or tcp://host:port; send raw bytes. 0 ok. */
int ta_syslog_send_bytes(const char *url, const void *data, size_t n);

/* Default ta_log_send_fn: format each row as RFC 5424 and UDP/TCP send. */
int ta_syslog_log_send(const char *url, const ta_log_accept_event_t *rows,
                       size_t n, void *ud);

/* Install ta_syslog_log_send as the Log dump sender (host). */
void ta_syslog_install_default_sender(void);

#ifdef __cplusplus
}
#endif
#endif
