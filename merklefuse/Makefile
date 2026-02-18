.PHONY: install test lint format clean help

# Default target
help:
	@echo "Available targets:"
	@echo "  install     - Install requirements"
	@echo "  test        - Run all tests"
	@echo "  test-unit   - Run unit tests only"
	@echo "  test-integration - Run integration tests only"
	@echo "  lint        - Run pylint"
	@echo "  format      - Run black formatter"
	@echo "  clean       - Clean up temporary files"
	@echo "  mount       - Mount filesystem (requires sudo)"

# Install dependencies
install:
	pip install -r requirements.txt

# Run all tests
test: test-unit test-integration

# Run unit tests (mocked filesystem operations)
test-unit:
	pytest tests/unit/ -v

# Run integration tests (real filesystem operations in /tmp)
test-integration:
	pytest tests/integration/ -v

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
