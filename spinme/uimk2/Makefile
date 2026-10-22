# uimk2 host tests. Builds into build/ (gitignored) and runs each test.

CC ?= cc
PYTHON ?= python3
FONT ?= /System/Library/Fonts/Helvetica.ttc
WARN := -std=c99 -pedantic -Wall -Wextra -Werror -O1 -g \
	-fsanitize=address,undefined -fno-omit-frame-pointer
BUILD := build

TESTS := $(BUILD)/test_arena $(BUILD)/test_bitmap

.PHONY: test test-glyphs clean

test: $(TESTS) test-glyphs
	@set -e; for t in $(TESTS); do ./$$t; done

# The generator's table checks, then the generated table compiles as C99.
test-glyphs: $(BUILD)/glyphs_12.o
	$(PYTHON) test_gen_glyphs.py

$(BUILD)/glyphs_12.c: gen_glyphs.py | $(BUILD)
	$(PYTHON) gen_glyphs.py $(FONT) 12 $@

$(BUILD)/glyphs_12.o: $(BUILD)/glyphs_12.c uimk2_glyphs.h
	$(CC) $(WARN) $(CFLAGS) -I. -c -o $@ $<

$(BUILD)/test_arena: test_arena.c uimk2_arena.c uimk2_arena.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_arena.c uimk2_arena.c

$(BUILD)/test_bitmap: test_bitmap.c uimk2_bitmap.c uimk2_bitmap.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_bitmap.c uimk2_bitmap.c

$(BUILD):
	mkdir -p $@

clean:
	rm -rf $(BUILD)
