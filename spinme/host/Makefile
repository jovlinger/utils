# spinme host tests (off-device redesign). Builds into build/ (gitignored).

CC ?= cc
WARN := -std=c99 -pedantic -Wall -Wextra -Werror -O1 -g \
	-fsanitize=address,undefined -fno-omit-frame-pointer
BUILD := build

TESTS := $(BUILD)/test_smoke $(BUILD)/test_event_envelope $(BUILD)/test_queue

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

$(BUILD):
	mkdir -p $(BUILD)

clean:
	rm -rf $(BUILD)
