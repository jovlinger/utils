#include "ta_net_sntp.h"

#include <Arduino.h>
#include <time.h>

extern "C" void ta_net_sntp_after_wifi(void) {
  setenv("TZ", "EST5EDT,M3.2.0/2,M11.1.0/2", 1);
  tzset();
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
}
