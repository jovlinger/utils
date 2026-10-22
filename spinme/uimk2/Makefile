CC = cc
CFLAGS = -std=c11 -Wall -Wextra -Werror -g

.PHONY: test clean

test_arena: test_arena.c arena.c arena.h
	$(CC) $(CFLAGS) -o $@ test_arena.c arena.c

test_bitmap: test_bitmap.c bitmap.c bitmap.h
	$(CC) $(CFLAGS) -o $@ test_bitmap.c bitmap.c

test: test_arena test_bitmap
	./test_arena
	./test_bitmap
	python3 test_glyphgen.py

clean:
	rm -rf test_arena test_arena.dSYM test_bitmap test_bitmap.dSYM
