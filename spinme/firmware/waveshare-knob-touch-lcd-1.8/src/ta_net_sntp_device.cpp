#include "ta_net_sntp.h"

#include "ta_runtime_cfg.h"

#include <Arduino.h>
#include <time.h>

extern "C" void ta_net_sntp_after_wifi(void) {
  const ta_runtime_cfg_t *rc;

  (void)ta_runtime_cfg_load(nullptr);
  rc = ta_runtime_cfg();
  setenv("TZ", rc->timezone, 1);
  tzset();
  /* Primary from KV; NIST stays as a fixed backup pool. */
  configTime(0, 0, rc->ntp_host, "time.nist.gov");
}
