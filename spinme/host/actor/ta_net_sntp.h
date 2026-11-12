/* Net-owned SNTP: call after WiFi is up. Host stub records the request. */
#ifndef SPINME_TA_NET_SNTP_H
#define SPINME_TA_NET_SNTP_H

#ifdef __cplusplus
extern "C" {
#endif

void ta_net_sntp_after_wifi(void);
/* Host tests: 1 after a successful after_wifi call. */
int ta_net_sntp_started(void);
void ta_net_sntp_reset(void);

#ifdef __cplusplus
}
#endif

#endif
