HOST_CC ?= cc
HOST_CFLAGS = -std=c99 -Wall -Wextra -Werror -pedantic

HOST_PYTHON ?= python3
GLYPH_FONT ?= /System/Library/Fonts/Helvetica.ttc
GLYPH_PX ?= 12

test: test_glyphs test_arena test_bitmap test_glyph_kind
	./test_arena
	./test_bitmap
	./test_glyph_kind

test_glyphs:
	PYTHONDONTWRITEBYTECODE=1 $(HOST_PYTHON) -m unittest -q test_glyphs

glyphs_gen.h: gen_glyphs.py
	$(HOST_PYTHON) gen_glyphs.py $(GLYPH_FONT) $(GLYPH_PX) $@

test_arena: test_arena.c arena.c arena.h
	$(HOST_CC) $(HOST_CFLAGS) -o $@ test_arena.c arena.c

test_bitmap: test_bitmap.c bitmap.c bitmap.h
	$(HOST_CC) $(HOST_CFLAGS) -o $@ test_bitmap.c bitmap.c

test_glyph_kind: test_glyph_kind.c glyph.c glyph.h glyphs_gen.h bitmap.c bitmap.h arena.c arena.h
	$(HOST_CC) $(HOST_CFLAGS) -o $@ test_glyph_kind.c glyph.c bitmap.c arena.c

clean:
	rm -f test_arena test_bitmap test_glyph_kind glyphs_gen.h
.PHONY: test test_glyphs clean
