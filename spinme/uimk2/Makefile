# uimk2 host tests. Builds into build/ (gitignored) and runs each test.

CC ?= cc
PYTHON ?= python3
FONT ?= /System/Library/Fonts/Helvetica.ttc
WARN := -std=c99 -pedantic -Wall -Wextra -Werror -O1 -g \
	-fsanitize=address,undefined -fno-omit-frame-pointer
BUILD := build

TESTS := $(BUILD)/test_arena $(BUILD)/test_bitmap $(BUILD)/test_line \
	$(BUILD)/test_event $(BUILD)/test_sched $(BUILD)/test_measure \
	$(BUILD)/test_follow $(BUILD)/test_zlist $(BUILD)/test_host \
	$(BUILD)/test_integ $(BUILD)/test_blit

.PHONY: test test-glyphs clean bench bench-ui bench-blit integ-bench

# Timed host UI binary. Does not inherit WARN: no -fsanitize, and -O2
# rather than the test binary's -O1, so us/op is a fair host number.
# CFLAGS is intentionally omitted so a sanitize flag cannot leak in.
BENCH_CFLAGS := -std=c99 -pedantic -Wall -Wextra -Werror -O2

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

$(BUILD)/test_event: test_event.c uimk2_event.c uimk2_event.h uimk2_config.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_event.c uimk2_event.c

$(BUILD)/test_sched: test_sched.c uimk2_sched.c uimk2_sched.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_sched.c uimk2_sched.c

$(BUILD)/test_measure: test_measure.c uimk2_bitmap.c uimk2_blit.c \
		uimk2_bitmap.h uimk2_blit.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_measure.c uimk2_bitmap.c uimk2_blit.c

$(BUILD)/test_bitmap: test_bitmap.c uimk2_bitmap.c uimk2_blit.c \
		uimk2_bitmap.h uimk2_blit.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_bitmap.c uimk2_bitmap.c uimk2_blit.c

LINE_SRC := test_line.c uimk2_line.c uimk2_bitmap.c uimk2_blit.c uimk2_arena.c
LINE_HDR := uimk2_line.h uimk2_bitmap.h uimk2_blit.h uimk2_arena.h \
	uimk2_glyphs.h

$(BUILD)/test_line: $(LINE_SRC) $(LINE_HDR) $(BUILD)/glyphs_12.c | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -I. -o $@ $(LINE_SRC) $(BUILD)/glyphs_12.c

FOLLOW_SRC := test_follow.c uimk2_follow.c uimk2_line.c uimk2_bitmap.c \
	uimk2_blit.c uimk2_arena.c uimk2_sched.c

$(BUILD)/test_follow: $(FOLLOW_SRC) uimk2_follow.h $(LINE_HDR) uimk2_sched.h \
		$(BUILD)/glyphs_12.c | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -I. -o $@ $(FOLLOW_SRC) $(BUILD)/glyphs_12.c

$(BUILD)/test_zlist: test_zlist.c uimk2_zlist.c uimk2_zlist.h \
		uimk2_event.c uimk2_event.h uimk2_config.h | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_zlist.c uimk2_zlist.c uimk2_event.c

$(BUILD)/test_blit: test_blit.c uimk2_blit.c uimk2_blit.h uimk2_config.h \
		| $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_blit.c uimk2_blit.c

HOST_SRC := test_host.c uimk2_host.c uimk2_zlist.c uimk2_event.c
HOST_HDR := uimk2_host.h uimk2_zlist.h uimk2_event.h uimk2_config.h

$(BUILD)/test_host: $(HOST_SRC) $(HOST_HDR) | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ $(HOST_SRC)

BENCH_SRC := bench_ui.c uimk2_host.c uimk2_zlist.c uimk2_event.c
BENCH_HDR := uimk2_host.h uimk2_zlist.h uimk2_event.h uimk2_config.h

$(BUILD)/bench_ui: $(BENCH_SRC) $(BENCH_HDR) bench_time.h | $(BUILD)
	$(CC) $(BENCH_CFLAGS) -o $@ $(BENCH_SRC) -lm

bench bench-ui: $(BUILD)/bench_ui
	./$(BUILD)/bench_ui

$(BUILD)/bench_blit: bench_blit.c uimk2_blit.c uimk2_blit.h uimk2_config.h \
		bench_time.h | $(BUILD)
	$(CC) $(BENCH_CFLAGS) -o $@ bench_blit.c uimk2_blit.c -lm

bench-blit: $(BUILD)/bench_blit
	./$(BUILD)/bench_blit

# Timed Core B integration sequence. No -fsanitize (BENCH_CFLAGS).
# From this directory: make integ-bench
# N=100, sample stdev, same clock as bench-ui. Writes build/integ_bench.txt.
INTEG_SRC := integ_script.c uimk2_host.c uimk2_zlist.c uimk2_event.c
INTEG_HDR := integ_script.h uimk2_host.h uimk2_zlist.h uimk2_event.h \
	uimk2_config.h

$(BUILD)/test_integ: test_integ.c $(INTEG_SRC) $(INTEG_HDR) | $(BUILD)
	$(CC) $(WARN) $(CFLAGS) -o $@ test_integ.c $(INTEG_SRC)

$(BUILD)/integ_bench: integ_bench.c $(INTEG_SRC) $(INTEG_HDR) bench_time.h \
		| $(BUILD)
	$(CC) $(BENCH_CFLAGS) -o $@ integ_bench.c $(INTEG_SRC) -lm

integ-bench: $(BUILD)/integ_bench
	./$(BUILD)/integ_bench

$(BUILD):
	mkdir -p $@

clean:
	rm -rf $(BUILD)
