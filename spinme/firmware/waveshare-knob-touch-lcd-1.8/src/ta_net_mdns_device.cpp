/* Device mDNS: Arduino ESPmDNS advertises <hostname>.local. */
#include <ESPmDNS.h>

extern "C" int ta_net_mdns_advertise_device(const char *hostname) {
    static int begun;

    if (hostname == nullptr || hostname[0] == '\0') {
        hostname = "spinme";
    }
    if (!begun) {
        if (!MDNS.begin(hostname)) {
            return -1;
        }
        begun = 1;
    }
    return 0;
}
