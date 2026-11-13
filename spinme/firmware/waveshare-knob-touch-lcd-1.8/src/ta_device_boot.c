#include "ta_device_boot.h"

#include "ta_controller.h"
#include "ta_draw_events.h"
#include "ta_init.h"
#include "ta_kv.h"
#include "ta_log_accept.h"
#include "ta_logger.h"
#include "ta_queue.h"
#include "ta_http_actor.h"
#include "ta_net_events.h"
#include "ta_registry.h"
#include "ta_router.h"
#include "ta_runtime_cfg.h"
#include "ta_sched_events.h"
#include "ta_test_actor.h"

#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "ta";

static int g_fabric_up;
static TaskHandle_t g_fabric_task;

/* Draw's MP/SC queue: producers on any task (MPD, Net completions, the
 * albumart decoder) push; only the Draw task pumps. Bound before the
 * activation posts below so DRAW_SET_SHAPE_STACK waits for the glass glue. */
#define TA_DRAW_QUEUE_CAP 32
static ta_event_envelope_t g_draw_slots[TA_DRAW_QUEUE_CAP];
static ta_queue_t g_draw_q;

ta_queue_t *ta_device_draw_queue(void) {
    return &g_draw_q;
}

static void fabric_task(void *arg) {
    (void)arg;
    for (;;) {
        /* Logger only. Scheduler advances via ta_device_tick_ms from Draw. */
        (void)ta_logger_drain(8);
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

void ta_device_boot(void) {
    ta_runtime_cfg_t rc;

    ta_registry_reset();
    ta_init_reset();
    ta_logger_reset();
    ta_sched_reset();
    ta_draw_reset();
    ta_net_reset();
    ta_http_reset();
    ta_mpd_reset();
    ta_sonos_reset();
    ta_router_reset();

    /* Factory KV seeds roster + runtime settings; later PUT /kv overwrites. */
    ta_kv_install_factory();
    (void)ta_runtime_cfg_load(&rc);

    (void)ta_init_add_entry(TA_LOGGER_NAME, ta_logger_start);
    (void)ta_init_add_entry(TA_DRAW_NAME, ta_draw_start);
    (void)ta_init_add_entry(TA_NET_NAME, ta_net_start);
    (void)ta_init_add_entry(TA_HTTP_NAME, ta_http_start);
    (void)ta_init_add_entry(TA_SCHED_NAME, ta_sched_start);
    (void)ta_init_add_entry(TA_CONTROLLER_NAME, ta_router_start);
    (void)ta_init_add_entry(TA_MPD_NAME, ta_mpd_start);
    (void)ta_init_add_entry(TA_SONOS_NAME, ta_sonos_start);
    (void)ta_init_add_entry(TA_TEST_NAME, ta_test_start);
    (void)ta_init_add_entry("Log", ta_log_start);

    ta_init_run_entries();
    ta_logger_set_policy(0, TA_LOG_POLICY_EXTERNAL);
    if (ta_queue_init(&g_draw_q, g_draw_slots, TA_DRAW_QUEUE_CAP) != 0) {
        ESP_LOGE(TAG, "draw queue init fail");
        g_fabric_up = 0;
        return;
    }
    ta_draw_bind_queue(&g_draw_q);

    if (ta_registry_lookup(TA_LOGGER_NAME) == NULL ||
        ta_registry_lookup(TA_DRAW_NAME) == NULL ||
        ta_registry_lookup(TA_NET_NAME) == NULL ||
        ta_registry_lookup(TA_SCHED_NAME) == NULL ||
        ta_registry_lookup(TA_CONTROLLER_NAME) == NULL ||
        ta_registry_lookup(TA_MPD_NAME) == NULL) {
        ESP_LOGE(TAG, "register fail");
        g_fabric_up = 0;
        return;
    }

    if (xTaskCreatePinnedToCore(fabric_task, "ta_fabric", 4096, NULL, 1,
                                &g_fabric_task, 0) != pdPASS) {
        ESP_LOGE(TAG, "task create fail");
        g_fabric_up = 0;
        return;
    }

    g_fabric_up = 1;
    ESP_LOGI(TAG,
             "fabric up: Logger Draw Net Http Scheduler Controller MPD Sonos");
    (void)ta_logger_emit(1, "Init", 0, 1, "fabric_boot");

    /* Activate the MVP face: Router -> MPDController, which arms the
     * Scheduler poll cadence (CTRL_POLL -> NET_POLL). Scheduler time only
     * advances via ta_device_tick_ms from the Draw task, so the first
     * poll fires after Net is bound to player_http. */
    {
        ta_event_envelope_t env;

        ta_env_clear(&env);
        env.event.type = TA_EV_SET_ROUTE;
        env.session_id = 1;
        (void)ta_env_set_src(&env, "Init");
        (void)ta_event_set_ctrl_set_route(&env.event, TA_MPD_NAME);
        if (ta_registry_post(TA_CONTROLLER_NAME, &env) != 0) {
            ESP_LOGE(TAG, "set route fail");
        }
        ta_env_clear(&env);
        env.event.type = TA_EV_CTRL_SET_ACTIVE;
        env.session_id = 1;
        (void)ta_env_set_src(&env, "Init");
        if (ta_registry_post(TA_CONTROLLER_NAME, &env) != 0) {
            ESP_LOGE(TAG, "set active fail");
        }
        /* Draw cadences: 1 Hz clock/idle tick, title scroll from KV. */
        if (ta_sched_arm_clock_1hz(TA_DRAW_NAME, 1) != 0 ||
            ta_sched_arm_scroll(TA_DRAW_NAME, 1, (int)rc.scroll_ms) != 0) {
            ESP_LOGE(TAG, "draw cadence arm fail");
        }
        printf("ta route=%s poll_ms=%u scroll_ms=%u blank_s=%u mpd=%s\n",
               ta_router_current_target(), (unsigned)TA_MPD_POLL_MS,
               rc.scroll_ms, rc.screen_blank_s, rc.mpd_host);
    }
}

void ta_device_tick_ms(uint32_t now_ms) {
    static uint32_t last_ms;
    static int primed;

    if (!primed) {
        primed = 1;
        last_ms = now_ms;
        return;
    }
    if (now_ms != last_ms) {
        ta_sched_advance_ms(now_ms - last_ms);
        last_ms = now_ms;
    }
}

int ta_device_fabric_up(void) {
    return g_fabric_up;
}
