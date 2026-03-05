.PHONY: help install dev test lint format clean docs build release

# Colors for output
BOLD=\033[1m
CYAN=\033[36m
GREEN=\033[32m
RESET=\033[0m

help:
	@echo "$(BOLD)gcc-evo Development Makefile$(RESET)"
	@echo ""
	@echo "$(CYAN)Installation:$(RESET)"
	@echo "  make install       - Install package with all extras"
	@echo "  make install-dev   - Install with dev dependencies"
	@echo "  make install-docs  - Install with documentation dependencies"
	@echo ""
	@echo "$(CYAN)Testing & Quality:$(RESET)"
	@echo "  make test          - Run all tests with coverage"
	@echo "  make test-unit     - Run unit tests only"
	@echo "  make test-int      - Run integration tests only"
	@echo "  make lint          - Run all linters"
	@echo "  make format        - Auto-format code (black, isort)"
	@echo "  make security      - Run security scanners (bandit, safety)"
	@echo ""
	@echo "$(CYAN)Documentation:$(RESET)"
	@echo "  make docs          - Build documentation"
	@echo "  make docs-serve    - Build and serve docs locally"
	@echo ""
	@echo "$(CYAN)Build & Release:$(RESET)"
	@echo "  make build         - Build distribution packages"
	@echo "  make clean         - Remove build artifacts"
	@echo "  make clean-all     - Remove all generated files"
	@echo ""
	@echo "$(CYAN)Development:$(RESET)"
	@echo "  make dev-shell     - Start interactive Python shell with env"
	@echo "  make requirements  - Generate requirements.txt"

# Installation targets
install:
	pip install -e ".[dev,docs,local-llm]"

install-dev:
	pip install -e ".[dev]"

install-docs:
	pip install -e ".[docs]"

# Testing targets
test:
	pytest tests/ -v --cov=gcc_evolution --cov-report=html --cov-report=term-missing

test-unit:
	pytest tests/unit/ -v --cov=gcc_evolution

test-int:
	pytest tests/integration/ -v -s

test-fast:
	pytest tests/ -v --tb=short -x

# Linting targets
lint: lint-flake8 lint-mypy lint-pylint

lint-flake8:
	@echo "$(GREEN)Running flake8...$(RESET)"
	flake8 gcc_evolution/ --count --statistics --max-line-length=100

lint-mypy:
	@echo "$(GREEN)Running mypy...$(RESET)"
	mypy gcc_evolution/ --ignore-missing-imports || true

lint-pylint:
	@echo "$(GREEN)Running pylint...$(RESET)"
	pylint gcc_evolution/ --exit-zero --max-line-length=100 || true

# Formatting targets
format: format-black format-isort

format-black:
	@echo "$(GREEN)Running black...$(RESET)"
	black gcc_evolution/ tests/

format-isort:
	@echo "$(GREEN)Running isort...$(RESET)"
	isort gcc_evolution/ tests/

format-check:
	black --check gcc_evolution/ tests/
	isort --check-only gcc_evolution/ tests/

# Security targets
security: security-bandit security-safety

security-bandit:
	@echo "$(GREEN)Running bandit...$(RESET)"
	bandit -r gcc_evolution/ -f json -o bandit-report.json || true
	@echo "Report: bandit-report.json"

security-safety:
	@echo "$(GREEN)Running safety...$(RESET)"
	safety check --json || true

# Documentation targets
docs:
	@echo "$(GREEN)Building documentation...$(RESET)"
	cd docs && make html
	@echo "$(GREEN)Docs built: docs/_build/html/index.html$(RESET)"

docs-serve: docs
	@echo "$(GREEN)Serving docs at http://localhost:8000$(RESET)"
	cd docs/_build/html && python -m http.server 8000

# Build targets
build: clean
	@echo "$(GREEN)Building distributions...$(RESET)"
	python -m build
	@echo "$(GREEN)Build complete: dist/$(RESET)"

build-wheel:
	python -m build --wheel

build-sdist:
	python -m build --sdist

# Cleaning targets
clean:
	@echo "$(GREEN)Removing build artifacts...$(RESET)"
	rm -rf build/ dist/ *.egg-info .eggs/ .pytest_cache/ .mypy_cache/ .coverage htmlcov/ *.pyc *.pyo __pycache__/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete

clean-all: clean
	@echo "$(GREEN)Removing all generated files...$(RESET)"
	rm -rf .tox/ .venv/ venv/ .eggs/ *.egg-info/ docs/_build/ coverage.xml bandit-report.json
	find . -type f -name ".DS_Store" -delete

clean-caches:
	@echo "$(GREEN)Clearing Python caches...$(RESET)"
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true

# Development utilities
dev-shell:
	@echo "$(GREEN)Starting Python shell with gcc_evolution...$(RESET)"
	python -c "import gcc_evolution; print(f'gcc-evo loaded'); import IPython; IPython.embed()"

requirements:
	@echo "$(GREEN)Generating requirements.txt...$(RESET)"
	pip freeze > requirements.txt
	@echo "Generated: requirements.txt"

version:
	@python -c "from gcc_evolution import __version__; print(f'gcc-evo v{__version__}')"

check: lint format-check
	@echo "$(GREEN)All checks passed!$(RESET)"

ci: test lint security
	@echo "$(GREEN)CI pipeline complete!$(RESET)"

# Default target
.DEFAULT_GOAL := help
