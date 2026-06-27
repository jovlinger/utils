.PHONY: install test all-tests lint format clean help binlinks

PYTEST := .venv/bin/python

$(PYTEST): requirements.txt
	../create_pipenv.sh --sync merklefuse

# Default target
help:
	@echo "Available targets:"
	@echo "  install          - Install requirements"
	@echo "  test             - Run unit tests (fast)"
	@echo "  all-tests        - Unit + integration tests"
	@echo "  test-unit        - Run unit tests only"
	@echo "  test-integration - Run integration tests only"
	@echo "  lint             - Run pylint"
	@echo "  format           - Run black formatter"
	@echo "  clean            - Clean up temporary files"
	@echo "  mount            - Mount filesystem (requires sudo)"

# Install dependencies
install: $(PYTEST)

test: test-unit

all-tests: test-unit test-integration

# Run unit tests (mocked filesystem operations)
test-unit: $(PYTEST)
	@mkdir -p data
	$(PYTEST) -m pytest tests/unit/ -v

# Run integration tests (real filesystem operations in /tmp)
test-integration: $(PYTEST)
	$(PYTEST) -m pytest tests/integration/ -v

# Run linting
lint:
	pylint merklefuse/ tests/

# Format code
format:
	black merklefuse/ tests/

# Clean up
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf build/ dist/ .pytest_cache/ .coverage htmlcov/

# Mount filesystem (example - requires sudo)
mount:
	sudo python -m merklefuse.cli /mnt/merklefuse --foreground

# Development setup
dev-setup: install
	mkdir -p tests/unit tests/integration
	mkdir -p merklefuse

binlinks:
	@:
