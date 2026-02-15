.PHONY: install test lint black clean help docker docker-test

# Default target
help:
	@echo "Available targets:"
	@echo "  setup       - Create virtual environment"
	@echo "  install     - Install requirements (requires activated venv)"
	@echo "  test        - Run all tests"
	@echo "  test-unit   - Run unit tests only"
	@echo "  test-integration - Run integration tests only"
	@echo "  lint        - Run pylint"
	@echo "  black       - Run black formatter"
	@echo "  clean       - Clean up temporary files"
	@echo "  mount       - Mount filesystem (requires sudo)"
	@echo "  docker      - Build and run in Docker container"
	@echo "  docker-test - Run tests in Docker container"

# Setup virtual environment and install dependencies
setup:
	@echo "Creating virtual environment..."
	python3 -m venv venv
	@echo ""
	@echo "Virtual environment created!"
	@echo "IMPORTANT: You must activate it before running 'make install':"
	@echo "  source venv/bin/activate"
	@echo "  make install"
	@echo ""

# Install dependencies
install:
	@which pip3 > /dev/null || (echo "Run 'make setup' to create a virtual environment, then 'source venv/bin/activate' to activate it." && exit 1)
	pip3 install -r requirements.txt 2>/dev/null || (echo "Run 'make setup' to create a virtual environment, then 'source venv/bin/activate' to activate it." && exit 1)

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
black:
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

# Docker commands
docker:
	docker-compose build
	docker-compose run --rm merklefuse

docker-test:
	docker-compose build
	docker-compose run --rm merklefuse make test

# Development setup
dev-setup: install
	mkdir -p tests/unit tests/integration
	mkdir -p merklefuse
