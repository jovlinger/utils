#include "ta_debug.h"

#include "ta_draw_glass.h"
#include "ta_log_accept.h"

#include <stdio.h>

int ta_debug_capture_and_log(uint32_t now_ms) {
    char msg[TA_LOG_MSG_MAX];
    const ta_follow_chrome_t *chrome;
    const char *title;
    int n;

    chrome = ta_glass_chrome();
    title = ta_glass_text(TA_DRAW_TEXT_TITLE);
    if (title == NULL) {
        title = "";
    }
    n = snprintf(msg, sizeof(msg), "dbg p=%d d=%d pl=%d pg=%u n=%u t=%.8s",
                 ta_glass_polled(), ta_glass_desired(), ta_glass_playing(),
                 ta_glass_page(),
                 chrome != NULL ? (unsigned)chrome->n : 0u, title);
    if (n < 0) {
        return -1;
    }
    if (ta_log_accept(now_ms, msg) != 0) {
        /* Still try dump of whatever is buffered. */
        (void)ta_log_dump(now_ms);
        return -1;
    }
    return ta_log_dump(now_ms);
}
