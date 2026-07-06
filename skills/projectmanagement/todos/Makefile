# skills/projectmanagement/todos -- branch-bound todo ticket CLI.
BINLINKS := ../../../binlinks
APPLE_SRC := apple_embedder/nlce_embed.swift
APPLE_BIN := apple_embedder/nlce-embed

.PHONY: binlinks test all-tests apple-embedder

binlinks:
	ln -sf ../skills/projectmanagement/todos/todo.py $(BINLINKS)/todo

# No venv wired up yet; run `python3 -m pytest` by hand in this dir.
test:
	@:

all-tests: test

# Build the macOS-only Apple NLContextualEmbedding sidecar (requires swiftc,
# macOS 14+). Optional: only needed for TODO_EMBEDDER=apple.
apple-embedder: $(APPLE_BIN)

$(APPLE_BIN): $(APPLE_SRC)
	swiftc -O -o $(APPLE_BIN) $(APPLE_SRC)
