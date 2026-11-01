# spinme host tests (off-device redesign). Builds into build/ (gitignored).

CC ?= cc
WARN := -std=c99 -pedantic -Wall -Wextra -Werror -O1 -g \
	-fsanitize=address,undefined -fno-omit-frame-pointer
BUILD := build

TESTS := $(BUILD)/test_smoke $(BUILD)/test_event_envelope $(BUILD)/test_queue \
	$(BUILD)/test_registry_logger $(BUILD)/test_router $(BUILD)/test_isr_mail \
	$(BUILD)/test_kv $(BUILD)/test_draw_events $(BUILD)/test_net_events \
	$(BUILD)/test_sched_events $(BUILD)/test_controller

.PHONY: test clean

# test_draw_glass_contract is intentionally red until Draw paint lands.
RED_TESTS := $(BUILD)/test_draw_glass_contract

test: $(TESTS) $(RED_TESTS)
	@set -e; for t in $(TESTS); do ./$$t; done
	@set -e; for t in $(RED_TESTS); do \
		if ./$$t; then \
			echo "UNEXPECTED GREEN: $$t must stay red until Draw impl"; \
			exit 1; \
		else \
			echo "red as expected: $$t"; \
		fi; \
	done

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

DRAW_SRCS := test_draw_events.c ta_draw_events.c ta_registry.c ta_event.c
$(BUILD)/test_draw_events: $(DRAW_SRCS) ta_draw_events.h ta_registry.h \
		ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(DRAW_SRCS) -lpthread

NET_SRCS := test_net_events.c ta_net_events.c ta_registry.c ta_event.c
$(BUILD)/test_net_events: $(NET_SRCS) ta_net_events.h ta_registry.h ta_event.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(NET_SRCS) -lpthread

SCHED_SRCS := test_sched_events.c ta_sched_events.c ta_registry.c ta_event.c
$(BUILD)/test_sched_events: $(SCHED_SRCS) ta_sched_events.h ta_registry.h \
		ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(SCHED_SRCS) -lpthread

CTRL_SRCS := test_controller.c ta_controller.c ta_router.c ta_draw_events.c \
	ta_net_events.c ta_registry.c ta_event.c
$(BUILD)/test_controller: $(CTRL_SRCS) ta_controller.h ta_router.h \
		ta_draw_events.h ta_net_events.h ta_registry.h ta_event.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(CTRL_SRCS) -lpthread

$(BUILD)/test_draw_glass_contract: test_draw_glass_contract.c | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_draw_glass_contract.c

$(BUILD):
	mkdir -p $(BUILD)

clean:
	rm -rf $(BUILD)
