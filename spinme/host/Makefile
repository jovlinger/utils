# spinme host tests (off-device redesign). Builds into build/ (gitignored).

CC ?= cc
WARN := -std=c99 -pedantic -Wall -Wextra -Werror -O1 -g \
	-fsanitize=address,undefined -fno-omit-frame-pointer
BUILD := build

TESTS := $(BUILD)/test_smoke $(BUILD)/test_event_envelope $(BUILD)/test_queue \
	$(BUILD)/test_registry_logger $(BUILD)/test_router $(BUILD)/test_isr_mail

.PHONY: test clean

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

$(BUILD):
	mkdir -p $(BUILD)

clean:
	rm -rf $(BUILD)
