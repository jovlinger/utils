# uimk2 host tests. Builds into build/ (gitignored) and runs each test.

CC ?= cc
WARN := -std=c99 -pedantic -Wall -Wextra -Werror -O1 -g \
	-fsanitize=address,undefined -fno-omit-frame-pointer
BUILD := build

TESTS := $(BUILD)/test_arena $(BUILD)/test_bitmap

.PHONY: test clean

test: $(TESTS)
	@set -e; for t in $(TESTS); do ./$$t; done

$(BUILD)/test_arena: test_arena.c uimk2_arena.c uimk2_arena.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_arena.c uimk2_arena.c

$(BUILD)/test_bitmap: test_bitmap.c uimk2_bitmap.c uimk2_bitmap.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_bitmap.c uimk2_bitmap.c

$(BUILD):
	mkdir -p $@

clean:
	rm -rf $(BUILD)
