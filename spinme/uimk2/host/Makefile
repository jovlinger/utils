HOST_CC ?= cc
HOST_CFLAGS = -std=c99 -Wall -Wextra -Werror -pedantic

test: test_arena
	./test_arena

test_arena: test_arena.c arena.c arena.h
	$(HOST_CC) $(HOST_CFLAGS) -o $@ test_arena.c arena.c

clean:
	rm -f test_arena
.PHONY: test clean
