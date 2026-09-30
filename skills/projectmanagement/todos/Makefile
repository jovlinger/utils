# skills/projectmanagement/todos -- branch-bound todo ticket CLI.
BINLINKS := ../../../binlinks
APPLE_SRC := apple_embedder/nlce_embed.swift
APPLE_BIN := apple_embedder/nlce-embed

.PHONY: binlinks test all-tests apple-embedder

binlinks:
	ln -sf ../skills/projectmanagement/todos/todo.py $(BINLINKS)/todo

# Fast suite: every surface minus the spawn-bound CLI files. `run-tests.py
# --list` shows the map; `--surface <name>` runs one.
test:
	./run-tests.py

all-tests:
	./run-tests.py --all

# Build the macOS-only Apple NLContextualEmbedding sidecar (requires swiftc,
# macOS 14+). Optional: only needed for TODO_EMBEDDER=apple.
apple-embedder: $(APPLE_BIN)

$(APPLE_BIN): $(APPLE_SRC)
	swiftc -O -o $(APPLE_BIN) $(APPLE_SRC)
