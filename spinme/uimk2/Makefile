CC = cc
CFLAGS = -std=c11 -Wall -Wextra -Werror -g

.PHONY: test clean

test_arena: test_arena.c arena.c arena.h
	$(CC) $(CFLAGS) -o $@ test_arena.c arena.c

test: test_arena
	./test_arena

clean:
	rm -rf test_arena test_arena.dSYM
