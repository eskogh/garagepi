PYTHON ?= python3
PIP ?= pip

.PHONY: freeze install dev test lint check-install-system

check-install-system:
	$(PYTHON) scripts/check_install_system.py

# Install project in editable mode
install: check-install-system
	$(PIP) install -e .

# Install with dev extras (pytest, ruff, black, etc.)
dev:
	$(PIP) install -e .[dev]

# Freeze all installed deps into requirements.txt
freeze:
	$(PIP) freeze > requirements.txt
	@echo "✅ requirements.txt updated."

# Run tests
test:
	pytest -v

# Run linting / formatting checks
lint:
	ruff check src/
	black --check src/
