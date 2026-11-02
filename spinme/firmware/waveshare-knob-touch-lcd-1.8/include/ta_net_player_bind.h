#ifndef SPINME_TA_NET_PLAYER_BIND_H
#define SPINME_TA_NET_PLAYER_BIND_H

#ifdef __cplusplus
extern "C" {
#endif

void ta_net_bind_player_http(void);
void ta_net_on_player_http_event(int player_http_event);

#ifdef __cplusplus
}
#endif

#endif
