#include "ta_net_sntp.h"

#include "ta_runtime_cfg.h"

static int g_started;

void ta_net_sntp_reset(void) {
    g_started = 0;
}

int ta_net_sntp_started(void) {
    return g_started;
}

#ifndef SPINME_TA_DEVICE
void ta_net_sntp_after_wifi(void) {
    (void)ta_runtime_cfg_load(NULL);
    g_started = 1;
}
#endif
