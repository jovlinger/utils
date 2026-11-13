# spinme host tests (off-device redesign). Builds into build/ (gitignored).
#
# Library: event/ shape/ actor/ base/.
# Tests: tests/local/ (PC). Post-flash drivers: tests/ondevice/.
# VPATH + -I keep #include "ta_*.h" and bare ta_*.c prerequisites working.

CC ?= cc
SRC_DIRS := event shape actor base
VPATH := tests/local $(SRC_DIRS)
INCLUDES := $(addprefix -I,$(SRC_DIRS))
WARN := -std=c99 -pedantic -Wall -Wextra -Werror -O1 -g \
	-fsanitize=address,undefined -fno-omit-frame-pointer $(INCLUDES)
BUILD := build

TESTS := $(BUILD)/test_smoke $(BUILD)/test_event_envelope $(BUILD)/test_queue \
	$(BUILD)/test_registry_logger $(BUILD)/test_router $(BUILD)/test_isr_mail \
	$(BUILD)/test_kv $(BUILD)/test_draw_events $(BUILD)/test_net_events \
	$(BUILD)/test_sched_events $(BUILD)/test_controller $(BUILD)/test_uilayout \
	$(BUILD)/test_shape_l2r $(BUILD)/test_text $(BUILD)/test_draw_update \
	$(BUILD)/test_draw_phase1 $(BUILD)/test_draw_phase2 \
	$(BUILD)/test_sched_cadence $(BUILD)/test_follow_chrome \
	$(BUILD)/test_hit_dispatch $(BUILD)/test_net_mpd $(BUILD)/test_viewport \
	$(BUILD)/test_artwork $(BUILD)/test_actor $(BUILD)/test_boot \
	$(BUILD)/test_net_kv_http $(BUILD)/test_all_init $(BUILD)/test_kv_actor \
	$(BUILD)/test_log_accept $(BUILD)/test_log_drain $(BUILD)/test_log_init \
	$(BUILD)/test_net_sntp $(BUILD)/test_shape_swap \
	$(BUILD)/test_kv_editor $(BUILD)/test_screenshots $(BUILD)/test_wire \
	$(BUILD)/test_net_http_event $(BUILD)/test_debug $(BUILD)/test_runtime_cfg \
	$(BUILD)/test_debug_all

.PHONY: test clean

TESTS := $(TESTS) $(BUILD)/test_under_image $(BUILD)/test_draw_glass_contract \
	$(BUILD)/test_input_isr $(BUILD)/test_mpd_net $(BUILD)/test_draw_glass_owner \
	$(BUILD)/test_xy_timed_redraw $(BUILD)/test_shape_draw \
	$(BUILD)/test_test_actor $(BUILD)/test_log_rings \
	$(BUILD)/test_http_actor

# ListEvents offers HTTP bodies via ta_net_http_event.
HTTP_EVENT := ta_net_http_event.c

# Draw is the glass owner: its actor pulls the whole glass model in.
DRAW_CORE := ta_draw_events.c ta_draw_glass.c ta_draw_update.c \
	ta_draw_phase1.c ta_draw_phase2.c ta_follow_chrome.c ta_hit_dispatch.c \
	ta_text.c ta_shape_l2r.c ta_shape_swap.c ta_shape_draw.c ta_chrome_icons.c \
	ta_wire.c ta_debug.c ta_log_accept.c ta_log_rings.c ta_kv_actor.c \
	ta_stack_compose.c ta_runtime_cfg.c ta_kv.c ta_uilayout.c ta_isr_mail.c \
	ta_queue.c $(HTTP_EVENT)
DRAW_HDRS := ta_draw_events.h ta_draw_glass.h ta_draw_update.h \
	ta_draw_phase1.h ta_draw_phase2.h ta_follow_chrome.h ta_hit_dispatch.h \
	ta_text.h ta_shape_l2r.h ta_shape_swap.h ta_shape_draw.h ta_chrome_icons.h \
	ta_wire.h ta_stack_compose.h ta_runtime_cfg.h ta_kv.h ta_uilayout.h \
	ta_isr_mail.h ta_queue.h ta_net_http_event.h

test: $(TESTS)
	@set -e; for t in $(TESTS); do ./$$t; done

$(BUILD)/test_smoke: test_smoke.c | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

$(BUILD)/test_event_envelope: test_event_envelope.c ta_event.c ta_event.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

$(BUILD)/test_queue: test_queue.c ta_queue.c ta_queue.h ta_event.c ta_event.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

REG_SRCS := test_registry_logger.c ta_registry.c ta_init.c ta_logger.c \
	ta_queue.c ta_event.c $(HTTP_EVENT)
$(BUILD)/test_registry_logger: $(REG_SRCS) ta_registry.h ta_init.h ta_logger.h \
		ta_queue.h ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

ROUTER_SRCS := test_router.c ta_router.c $(HTTP_EVENT) ta_registry.c \
	ta_event.c
$(BUILD)/test_router: $(ROUTER_SRCS) ta_router.h ta_net_http_event.h \
		ta_registry.h ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

$(BUILD)/test_debug_all: test_debug_all.c ta_router.c $(HTTP_EVENT) \
		ta_registry.c ta_event.c ta_router.h ta_net_http_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

ISR_SRCS := test_isr_mail.c ta_isr_mail.c ta_queue.c ta_event.c
$(BUILD)/test_isr_mail: $(ISR_SRCS) ta_isr_mail.h ta_queue.h ta_event.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

$(BUILD)/test_kv: test_kv.c ta_kv.c ta_runtime_cfg.c ta_kv.h ta_runtime_cfg.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

$(BUILD)/test_runtime_cfg: test_runtime_cfg.c ta_runtime_cfg.c ta_kv.c \
		ta_runtime_cfg.h ta_kv.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

DRAW_SRCS := test_draw_events.c $(DRAW_CORE) ta_registry.c ta_event.c
$(BUILD)/test_draw_events: $(DRAW_SRCS) $(DRAW_HDRS) ta_registry.h \
		ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

NET_SRCS := test_net_events.c ta_net_events.c $(HTTP_EVENT) \
	ta_sched_events.c ta_registry.c ta_event.c
$(BUILD)/test_net_events: $(NET_SRCS) ta_net_events.h ta_net_http_event.h \
		ta_sched_events.h ta_registry.h ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

SCHED_SRCS := test_sched_events.c ta_sched_events.c $(HTTP_EVENT) \
	ta_registry.c ta_event.c
$(BUILD)/test_sched_events: $(SCHED_SRCS) ta_sched_events.h ta_draw_events.h \
		ta_registry.h ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

CAD_SRCS := test_sched_cadence.c ta_sched_events.c $(HTTP_EVENT) \
	ta_registry.c ta_event.c
$(BUILD)/test_sched_cadence: $(CAD_SRCS) ta_sched_events.h ta_draw_events.h \
		ta_registry.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

$(BUILD)/test_follow_chrome: test_follow_chrome.c ta_follow_chrome.c \
		ta_uilayout.c ta_follow_chrome.h ta_uilayout.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

HIT_SRCS := test_hit_dispatch.c $(DRAW_CORE) ta_controller.c ta_router.c \
	ta_net_events.c ta_sched_events.c ta_registry.c ta_event.c
$(BUILD)/test_hit_dispatch: $(HIT_SRCS) $(DRAW_HDRS) ta_controller.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

MPD_SRCS := test_net_mpd.c ta_net_mpd.c ta_registry.c ta_event.c
$(BUILD)/test_net_mpd: $(MPD_SRCS) ta_net_mpd.h ta_net_events.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

$(BUILD)/test_viewport: test_viewport.c ta_viewport.c ta_uilayout.c \
		ta_viewport.h ta_uilayout.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

ART_SRCS := test_artwork.c ta_artwork.c ta_sched_events.c $(HTTP_EVENT) \
	ta_registry.c ta_event.c
$(BUILD)/test_artwork: $(ART_SRCS) ta_artwork.h ta_sched_events.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

CTRL_SRCS := test_controller.c ta_controller.c ta_router.c $(DRAW_CORE) \
	ta_net_events.c ta_sched_events.c ta_registry.c ta_event.c
$(BUILD)/test_controller: $(CTRL_SRCS) ta_controller.h ta_router.h \
		$(DRAW_HDRS) ta_net_events.h ta_net_http_event.h ta_sched_events.h \
		ta_registry.h ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

MPDNET_SRCS := test_mpd_net.c ta_controller.c ta_router.c $(DRAW_CORE) \
	ta_net_events.c ta_sched_events.c ta_registry.c ta_event.c
$(BUILD)/test_mpd_net: $(MPDNET_SRCS) ta_controller.h ta_router.h \
		$(DRAW_HDRS) ta_net_events.h ta_net_http_event.h ta_net_backend.h \
		ta_sched_events.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

OWNER_SRCS := test_draw_glass_owner.c ta_controller.c ta_router.c $(DRAW_CORE) \
	ta_input_isr.c ta_net_events.c ta_sched_events.c ta_registry.c ta_event.c
$(BUILD)/test_draw_glass_owner: $(OWNER_SRCS) ta_controller.h ta_router.h \
		$(DRAW_HDRS) ta_input_isr.h ta_net_events.h ta_net_http_event.h \
		ta_net_backend.h ta_sched_events.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

GLASS_SRCS := test_draw_glass_contract.c ta_draw_update.c ta_draw_phase1.c \
	ta_draw_phase2.c ta_under_image.c ta_shape_l2r.c ta_shape_swap.c \
	ta_shape_draw.c ta_uilayout.c
$(BUILD)/test_draw_glass_contract: $(GLASS_SRCS) ta_draw_update.h \
		ta_draw_phase1.h ta_draw_phase2.h ta_under_image.h \
		ta_shape_swap.h ta_shape_draw.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

$(BUILD)/test_under_image: test_under_image.c ta_under_image.c ta_uilayout.c \
		ta_under_image.h ta_draw_update.h ta_uilayout.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

IN_SRCS := test_input_isr.c ta_input_isr.c ta_isr_mail.c ta_queue.c ta_event.c
$(BUILD)/test_input_isr: $(IN_SRCS) ta_input_isr.h ta_isr_mail.h ta_queue.h \
		ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

$(BUILD)/test_uilayout: test_uilayout.c ta_uilayout.c ta_uilayout.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

L2R_SRCS := test_shape_l2r.c ta_shape_l2r.c ta_uilayout.c
$(BUILD)/test_shape_l2r: $(L2R_SRCS) ta_shape_l2r.h ta_uilayout.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

TEXT_SRCS := test_text.c ta_text.c ta_shape_l2r.c ta_uilayout.c
$(BUILD)/test_text: $(TEXT_SRCS) ta_text.h ta_shape_l2r.h ta_uilayout.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

UPD_SRCS := test_draw_update.c ta_draw_update.c ta_shape_l2r.c ta_uilayout.c
$(BUILD)/test_draw_update: $(UPD_SRCS) ta_draw_update.h ta_shape_l2r.h \
		ta_uilayout.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

P1_SRCS := test_draw_phase1.c ta_draw_phase1.c ta_shape_l2r.c ta_shape_swap.c \
	ta_shape_draw.c ta_uilayout.c
$(BUILD)/test_draw_phase1: $(P1_SRCS) ta_draw_phase1.h ta_draw_update.h \
		ta_shape_l2r.h ta_shape_swap.h ta_shape_draw.h ta_uilayout.h \
		ta_viewport.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

P2_SRCS := test_draw_phase2.c ta_draw_phase2.c ta_uilayout.c
$(BUILD)/test_draw_phase2: $(P2_SRCS) ta_draw_phase2.h ta_draw_update.h \
		ta_uilayout.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

$(BUILD)/test_actor: test_actor.c ta_actor.c ta_actor.h ta_registry.c \
		$(HTTP_EVENT) ta_registry.h ta_event.c ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

$(BUILD)/test_boot: test_boot.c ta_boot.c ta_boot.h ta_actor.c ta_kv.c \
		ta_runtime_cfg.c ta_registry.c $(HTTP_EVENT) ta_event.c ta_actor.h \
		ta_kv.h ta_registry.h ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

$(BUILD)/test_net_kv_http: test_net_kv_http.c ta_net_kv_http.c \
		ta_net_kv_http.h ta_boot.c ta_actor.c ta_kv.c ta_runtime_cfg.c \
		ta_registry.c $(HTTP_EVENT) ta_event.c | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

$(BUILD)/test_net_http_event: test_net_http_event.c $(HTTP_EVENT) \
		ta_test_actor.c ta_debug.c ta_log_accept.c ta_log_rings.c \
		ta_kv_actor.c ta_kv.c ta_runtime_cfg.c ta_router.c \
		ta_net_http_event.h ta_test_actor.h ta_registry.c ta_event.c \
		ta_net_events.h ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

$(BUILD)/test_all_init: test_all_init.c ta_all.c ta_all.h ta_registry.c \
		ta_event.c ta_registry.h ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

$(BUILD)/test_kv_actor: test_kv_actor.c ta_kv_actor.c ta_kv_actor.h ta_kv.c \
		ta_runtime_cfg.c ta_registry.c ta_event.c ta_net_http_event.c \
		ta_net_http_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

LOG_SRCS := ta_log_accept.c ta_log_rings.c ta_kv_actor.c ta_kv.c \
	ta_runtime_cfg.c ta_registry.c $(HTTP_EVENT) ta_event.c

$(BUILD)/test_log_accept: test_log_accept.c $(LOG_SRCS) | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

$(BUILD)/test_log_drain: test_log_drain.c $(LOG_SRCS) | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

$(BUILD)/test_log_rings: test_log_rings.c ta_log_rings.c ta_log_rings.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

$(BUILD)/test_log_init: test_log_init.c ta_log_accept.c ta_log_rings.c \
		ta_kv_actor.c ta_kv.c ta_runtime_cfg.c ta_all.c ta_registry.c \
		$(HTTP_EVENT) ta_event.c | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

$(BUILD)/test_net_sntp: test_net_sntp.c ta_net_sntp.c ta_runtime_cfg.c \
		ta_kv.c ta_net_sntp.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

$(BUILD)/test_shape_swap: test_shape_swap.c ta_shape_swap.c ta_draw_phase1.c \
		ta_draw_phase2.c ta_shape_l2r.c ta_shape_draw.c ta_uilayout.c \
		ta_viewport.c ta_shape_swap.h ta_draw_phase1.h ta_draw_phase2.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

$(BUILD)/test_kv_editor: test_kv_editor.c ta_kv_editor.c ta_kv.c \
		ta_runtime_cfg.c ta_shape_swap.c ta_uilayout.c ta_kv_editor.h \
		ta_kv.h ta_shape_swap.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

$(BUILD)/test_wire: test_wire.c ta_wire.c ta_shape_swap.c ta_uilayout.c \
		ta_registry.c ta_event.c ta_wire.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -DSPINME_NO_DEBUG_CHROME -o $@ $(filter %.c,$^) -lpthread

$(BUILD)/test_debug: test_debug.c $(DRAW_CORE) ta_viewport.c ta_registry.c \
		ta_event.c | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

SHOT_SRCS := test_screenshots.c ta_pack66_png.c ta_glyph_bin.c ta_kv_editor.c \
	ta_kv.c ta_runtime_cfg.c ta_draw_glass.c ta_draw_update.c \
	ta_draw_phase1.c ta_draw_phase2.c ta_follow_chrome.c ta_hit_dispatch.c \
	ta_text.c ta_shape_l2r.c ta_shape_swap.c ta_shape_draw.c ta_chrome_icons.c \
	ta_wire.c ta_debug.c ta_log_accept.c ta_log_rings.c ta_kv_actor.c \
	ta_stack_compose.c ta_uilayout.c ta_isr_mail.c ta_queue.c ta_viewport.c \
	ta_registry.c $(HTTP_EVENT) ta_event.c
$(BUILD)/test_screenshots: $(SHOT_SRCS) ta_pack66_png.h ta_glyph_bin.h \
		ta_kv_editor.h ta_draw_glass.h ta_follow_chrome.h ta_wire.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lz -lpthread

XYT_SRCS := test_xy_timed_redraw.c ta_uilayout.c ta_pack66_png.c \
	ta_glyph_bin.c ta_text.c ta_shape_l2r.c ta_shape_swap.c ta_shape_draw.c \
	ta_draw_phase1.c ta_viewport.c
$(BUILD)/test_xy_timed_redraw: $(XYT_SRCS) ta_uilayout.h ta_pack66_png.h \
		ta_glyph_bin.h ta_text.h ta_shape_l2r.h ta_shape_draw.h \
		ta_draw_phase1.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lz

$(BUILD)/test_shape_draw: test_shape_draw.c ta_shape_draw.c ta_uilayout.c \
		ta_shape_draw.h ta_uilayout.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^)

$(BUILD)/test_test_actor: test_test_actor.c ta_test_actor.c ta_net_http_event.c \
		ta_debug.c ta_log_accept.c ta_log_rings.c ta_kv_actor.c ta_kv.c \
		ta_runtime_cfg.c ta_registry.c ta_event.c ta_test_actor.h \
		ta_registry.h ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread

$(BUILD)/test_http_actor: test_http_actor.c ta_http_actor.c $(HTTP_EVENT) \
		ta_registry.c ta_event.c ta_http_actor.h ta_net_http_event.h \
		ta_registry.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(filter %.c,$^) -lpthread


$(BUILD):
	mkdir -p $(BUILD)

clean:
	rm -rf $(BUILD)
