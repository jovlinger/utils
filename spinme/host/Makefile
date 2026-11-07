# spinme host tests (off-device redesign). Builds into build/ (gitignored).

CC ?= cc
WARN := -std=c99 -pedantic -Wall -Wextra -Werror -O1 -g \
	-fsanitize=address,undefined -fno-omit-frame-pointer
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
	$(BUILD)/test_kv_editor

.PHONY: test clean

TESTS := $(TESTS) $(BUILD)/test_under_image $(BUILD)/test_draw_glass_contract \
	$(BUILD)/test_input_isr $(BUILD)/test_mpd_net $(BUILD)/test_draw_glass_owner

# Draw is the glass owner: its actor pulls the whole glass model in.
DRAW_CORE := ta_draw_events.c ta_draw_glass.c ta_draw_update.c \
	ta_draw_phase1.c ta_draw_phase2.c ta_follow_chrome.c ta_hit_dispatch.c \
	ta_text.c ta_shape_l2r.c ta_shape_swap.c ta_uilayout.c ta_isr_mail.c \
	ta_queue.c
DRAW_HDRS := ta_draw_events.h ta_draw_glass.h ta_draw_update.h \
	ta_draw_phase1.h ta_draw_phase2.h ta_follow_chrome.h ta_hit_dispatch.h \
	ta_text.h ta_shape_l2r.h ta_shape_swap.h ta_uilayout.h ta_isr_mail.h \
	ta_queue.h

test: $(TESTS)
	@set -e; for t in $(TESTS); do ./$$t; done

$(BUILD)/test_smoke: test_smoke.c | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_smoke.c

$(BUILD)/test_event_envelope: test_event_envelope.c ta_event.c ta_event.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_event_envelope.c ta_event.c

$(BUILD)/test_queue: test_queue.c ta_queue.c ta_queue.h ta_event.c ta_event.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_queue.c ta_queue.c ta_event.c -lpthread

REG_SRCS := test_registry_logger.c ta_registry.c ta_init.c ta_logger.c \
	ta_queue.c ta_event.c
$(BUILD)/test_registry_logger: $(REG_SRCS) ta_registry.h ta_init.h ta_logger.h \
		ta_queue.h ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(REG_SRCS) -lpthread

ROUTER_SRCS := test_router.c ta_router.c ta_registry.c ta_event.c
$(BUILD)/test_router: $(ROUTER_SRCS) ta_router.h ta_registry.h ta_event.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(ROUTER_SRCS) -lpthread

ISR_SRCS := test_isr_mail.c ta_isr_mail.c ta_queue.c ta_event.c
$(BUILD)/test_isr_mail: $(ISR_SRCS) ta_isr_mail.h ta_queue.h ta_event.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(ISR_SRCS) -lpthread

$(BUILD)/test_kv: test_kv.c ta_kv.c ta_kv.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_kv.c ta_kv.c

DRAW_SRCS := test_draw_events.c $(DRAW_CORE) ta_registry.c ta_event.c
$(BUILD)/test_draw_events: $(DRAW_SRCS) $(DRAW_HDRS) ta_registry.h \
		ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(DRAW_SRCS) -lpthread

NET_SRCS := test_net_events.c ta_net_events.c ta_registry.c ta_event.c
$(BUILD)/test_net_events: $(NET_SRCS) ta_net_events.h ta_registry.h ta_event.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(NET_SRCS) -lpthread

SCHED_SRCS := test_sched_events.c ta_sched_events.c ta_registry.c ta_event.c
$(BUILD)/test_sched_events: $(SCHED_SRCS) ta_sched_events.h ta_draw_events.h \
		ta_registry.h ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(SCHED_SRCS) -lpthread

CAD_SRCS := test_sched_cadence.c ta_sched_events.c ta_registry.c ta_event.c
$(BUILD)/test_sched_cadence: $(CAD_SRCS) ta_sched_events.h ta_draw_events.h \
		ta_registry.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(CAD_SRCS) -lpthread

$(BUILD)/test_follow_chrome: test_follow_chrome.c ta_follow_chrome.c \
		ta_uilayout.c ta_follow_chrome.h ta_uilayout.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_follow_chrome.c ta_follow_chrome.c \
		ta_uilayout.c

HIT_SRCS := test_hit_dispatch.c $(DRAW_CORE) ta_controller.c ta_router.c \
	ta_net_events.c ta_sched_events.c ta_registry.c ta_event.c
$(BUILD)/test_hit_dispatch: $(HIT_SRCS) $(DRAW_HDRS) ta_controller.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(HIT_SRCS) -lpthread

MPD_SRCS := test_net_mpd.c ta_net_mpd.c ta_registry.c ta_event.c
$(BUILD)/test_net_mpd: $(MPD_SRCS) ta_net_mpd.h ta_net_events.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(MPD_SRCS) -lpthread

$(BUILD)/test_viewport: test_viewport.c ta_viewport.c ta_uilayout.c \
		ta_viewport.h ta_uilayout.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_viewport.c ta_viewport.c ta_uilayout.c

ART_SRCS := test_artwork.c ta_artwork.c ta_sched_events.c ta_registry.c \
	ta_event.c
$(BUILD)/test_artwork: $(ART_SRCS) ta_artwork.h ta_sched_events.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(ART_SRCS) -lpthread

CTRL_SRCS := test_controller.c ta_controller.c ta_router.c $(DRAW_CORE) \
	ta_net_events.c ta_sched_events.c ta_registry.c ta_event.c
$(BUILD)/test_controller: $(CTRL_SRCS) ta_controller.h ta_router.h \
		$(DRAW_HDRS) ta_net_events.h ta_sched_events.h ta_registry.h \
		ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(CTRL_SRCS) -lpthread

MPDNET_SRCS := test_mpd_net.c ta_controller.c ta_router.c $(DRAW_CORE) \
	ta_net_events.c ta_sched_events.c ta_registry.c ta_event.c
$(BUILD)/test_mpd_net: $(MPDNET_SRCS) ta_controller.h ta_router.h \
		$(DRAW_HDRS) ta_net_events.h ta_net_backend.h ta_sched_events.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(MPDNET_SRCS) -lpthread

OWNER_SRCS := test_draw_glass_owner.c ta_controller.c ta_router.c $(DRAW_CORE) \
	ta_input_isr.c ta_net_events.c ta_sched_events.c ta_registry.c ta_event.c
$(BUILD)/test_draw_glass_owner: $(OWNER_SRCS) ta_controller.h ta_router.h \
		$(DRAW_HDRS) ta_input_isr.h ta_net_events.h ta_net_backend.h \
		ta_sched_events.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(OWNER_SRCS) -lpthread

GLASS_SRCS := test_draw_glass_contract.c ta_draw_update.c ta_draw_phase1.c \
	ta_draw_phase2.c ta_under_image.c ta_shape_l2r.c ta_shape_swap.c \
	ta_uilayout.c
$(BUILD)/test_draw_glass_contract: $(GLASS_SRCS) ta_draw_update.h \
		ta_draw_phase1.h ta_draw_phase2.h ta_under_image.h \
		ta_shape_swap.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(GLASS_SRCS)

$(BUILD)/test_under_image: test_under_image.c ta_under_image.c ta_uilayout.c \
		ta_under_image.h ta_draw_update.h ta_uilayout.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_under_image.c ta_under_image.c \
		ta_uilayout.c

IN_SRCS := test_input_isr.c ta_input_isr.c ta_isr_mail.c ta_queue.c ta_event.c
$(BUILD)/test_input_isr: $(IN_SRCS) ta_input_isr.h ta_isr_mail.h ta_queue.h \
		ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(IN_SRCS) -lpthread

$(BUILD)/test_uilayout: test_uilayout.c ta_uilayout.c ta_uilayout.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_uilayout.c ta_uilayout.c

L2R_SRCS := test_shape_l2r.c ta_shape_l2r.c ta_uilayout.c
$(BUILD)/test_shape_l2r: $(L2R_SRCS) ta_shape_l2r.h ta_uilayout.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(L2R_SRCS)

TEXT_SRCS := test_text.c ta_text.c ta_shape_l2r.c ta_uilayout.c
$(BUILD)/test_text: $(TEXT_SRCS) ta_text.h ta_shape_l2r.h ta_uilayout.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(TEXT_SRCS)

UPD_SRCS := test_draw_update.c ta_draw_update.c ta_shape_l2r.c ta_uilayout.c
$(BUILD)/test_draw_update: $(UPD_SRCS) ta_draw_update.h ta_shape_l2r.h \
		ta_uilayout.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(UPD_SRCS)

P1_SRCS := test_draw_phase1.c ta_draw_phase1.c ta_shape_l2r.c ta_shape_swap.c \
	ta_uilayout.c
$(BUILD)/test_draw_phase1: $(P1_SRCS) ta_draw_phase1.h ta_draw_update.h \
		ta_shape_l2r.h ta_shape_swap.h ta_uilayout.h ta_viewport.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(P1_SRCS)

P2_SRCS := test_draw_phase2.c ta_draw_phase2.c ta_uilayout.c
$(BUILD)/test_draw_phase2: $(P2_SRCS) ta_draw_phase2.h ta_draw_update.h \
		ta_uilayout.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(P2_SRCS)

$(BUILD)/test_actor: test_actor.c ta_actor.c ta_actor.h ta_registry.c \
		ta_registry.h ta_event.c ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_actor.c ta_actor.c ta_registry.c \
		ta_event.c -lpthread

$(BUILD)/test_boot: test_boot.c ta_boot.c ta_boot.h ta_actor.c ta_kv.c \
		ta_registry.c ta_event.c ta_actor.h ta_kv.h ta_registry.h \
		ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_boot.c ta_boot.c ta_actor.c ta_kv.c \
		ta_registry.c ta_event.c -lpthread

$(BUILD)/test_net_kv_http: test_net_kv_http.c ta_net_kv_http.c \
		ta_net_kv_http.h ta_boot.c ta_actor.c ta_kv.c ta_registry.c \
		ta_event.c | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_net_kv_http.c ta_net_kv_http.c \
		ta_boot.c ta_actor.c ta_kv.c ta_registry.c ta_event.c -lpthread

$(BUILD)/test_all_init: test_all_init.c ta_all.c ta_all.h ta_registry.c \
		ta_event.c ta_registry.h ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_all_init.c ta_all.c ta_registry.c \
		ta_event.c -lpthread

$(BUILD)/test_kv_actor: test_kv_actor.c ta_kv_actor.c ta_kv_actor.h ta_kv.c \
		ta_registry.c ta_event.c | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_kv_actor.c ta_kv_actor.c ta_kv.c \
		ta_registry.c ta_event.c -lpthread

LOG_SRCS := ta_log_accept.c ta_kv_actor.c ta_kv.c ta_registry.c ta_event.c

$(BUILD)/test_log_accept: test_log_accept.c $(LOG_SRCS) | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_log_accept.c $(LOG_SRCS) -lpthread

$(BUILD)/test_log_drain: test_log_drain.c $(LOG_SRCS) | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_log_drain.c $(LOG_SRCS) -lpthread

$(BUILD)/test_log_init: test_log_init.c ta_log_accept.c ta_kv_actor.c ta_kv.c \
		ta_all.c ta_registry.c ta_event.c | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_log_init.c ta_log_accept.c ta_kv_actor.c \
		ta_kv.c ta_all.c ta_registry.c ta_event.c -lpthread

$(BUILD)/test_net_sntp: test_net_sntp.c ta_net_sntp.c ta_net_sntp.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_net_sntp.c ta_net_sntp.c

$(BUILD)/test_shape_swap: test_shape_swap.c ta_shape_swap.c ta_draw_phase1.c \
		ta_draw_phase2.c ta_shape_l2r.c ta_uilayout.c ta_viewport.c \
		ta_shape_swap.h ta_draw_phase1.h ta_draw_phase2.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_shape_swap.c ta_shape_swap.c \
		ta_draw_phase1.c ta_draw_phase2.c ta_shape_l2r.c ta_uilayout.c \
		ta_viewport.c

$(BUILD)/test_kv_editor: test_kv_editor.c ta_kv_editor.c ta_kv.c ta_shape_swap.c \
		ta_uilayout.c ta_kv_editor.h ta_kv.h ta_shape_swap.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_kv_editor.c ta_kv_editor.c ta_kv.c \
		ta_shape_swap.c ta_uilayout.c

$(BUILD):
	mkdir -p $(BUILD)

clean:
	rm -rf $(BUILD)
