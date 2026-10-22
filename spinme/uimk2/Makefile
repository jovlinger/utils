CC = cc
CFLAGS = -std=c11 -Wall -Wextra -Werror -g

.PHONY: test clean

test_arena: test_arena.c arena.c arena.h
	$(CC) $(CFLAGS) -o $@ test_arena.c arena.c

test_bitmap: test_bitmap.c bitmap.c bitmap.h
	$(CC) $(CFLAGS) -o $@ test_bitmap.c bitmap.c

FONT = /System/Library/Fonts/Helvetica.ttc
GLYPH_SIZE = 16

glyphs_test.h: glyphgen.py
	python3 glyphgen.py $(FONT) $(GLYPH_SIZE) $@

test_glyph: test_glyph.c glyph.c glyph.h bitmap.c bitmap.h arena.c arena.h glyphs_test.h
	$(CC) $(CFLAGS) -o $@ test_glyph.c glyph.c bitmap.c arena.c

test: test_arena test_bitmap test_glyph
	./test_arena
	./test_bitmap
	./test_glyph
	python3 test_glyphgen.py

clean:
	rm -rf test_arena test_arena.dSYM test_bitmap test_bitmap.dSYM test_glyph test_glyph.dSYM glyphs_test.h
