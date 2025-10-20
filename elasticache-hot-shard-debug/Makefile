.PHONY: venv install dev test clean format lint run help

help:
	@echo "ElastiCache Monitor - Available commands:"
	@echo ""
	@echo "  make venv       - Create Python 3.12 venv with uv"
	@echo "  make install    - Install package with uv"
	@echo "  make dev        - Install with dev dependencies"
	@echo "  make test       - Run tests"
	@echo "  make format     - Format code with black"
	@echo "  make lint       - Lint code with ruff"
	@echo "  make clean      - Remove build artifacts"
	@echo "  make run        - Run the monitor (requires CLUSTER_ID and REDIS_PASSWORD)"
	@echo ""

venv:
	@echo "Creating Python 3.12 virtual environment with uv..."
	uv venv
	@echo ""
	@echo "✓ Virtual environment created at .venv"
	@echo "Activate with: source .venv/bin/activate"

install:
	@echo "Installing elasticache-monitor with uv..."
	@if [ ! -d ".venv" ]; then \
		echo "No venv found. Creating one first..."; \
		make venv; \
	fi
	uv pip install -e .

dev:
	@echo "Installing with dev dependencies..."
	uv pip install -e ".[dev]"

test:
	@echo "Running tests..."
	pytest tests/

format:
	@echo "Formatting code..."
	black src/
	ruff check --fix src/

lint:
	@echo "Linting code..."
	ruff check src/
	black --check src/

clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf .ruff_cache

run:
	@if [ -z "$(CLUSTER_ID)" ]; then \
		echo "Error: CLUSTER_ID not set"; \
		echo "Usage: make run CLUSTER_ID=my-cluster REDIS_PASSWORD=yourpass"; \
		exit 1; \
	fi
	@if [ -z "$(REDIS_PASSWORD)" ]; then \
		echo "Error: REDIS_PASSWORD not set"; \
		echo "Usage: make run CLUSTER_ID=my-cluster REDIS_PASSWORD=yourpass"; \
		exit 1; \
	fi
	elasticache-monitor -c $(CLUSTER_ID) -p $(REDIS_PASSWORD) -d $(DURATION)

