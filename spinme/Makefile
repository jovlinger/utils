.PHONY: binlinks test all-tests

CC ?= cc
CFLAGS = -std=c99 -Wall -Wextra -Werror -O1 -g

binlinks:
	@:

test: uimk2/test_arena uimk2/test_bitmap
	./uimk2/test_arena
	./uimk2/test_bitmap

uimk2/test_arena: uimk2/test_arena.c uimk2/arena.c uimk2/arena.h
	$(CC) $(CFLAGS) -o $@ uimk2/test_arena.c uimk2/arena.c

uimk2/test_bitmap: uimk2/test_bitmap.c uimk2/bitmap.c uimk2/bitmap.h
	$(CC) $(CFLAGS) -o $@ uimk2/test_bitmap.c uimk2/bitmap.c

all-tests: test
