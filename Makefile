.PHONY: freeze install dev test lint

# Install project in editable mode
install:
	pip install -e .

# Install with dev extras (pytest, ruff, black, etc.)
dev:
	pip install -e .[dev]

# Freeze all installed deps into requirements.txt
freeze:
	pip freeze > requirements.txt
	@echo "✅ requirements.txt updated."

# Run tests
test:
	pytest -v

# Run linting / formatting checks
lint:
	ruff check src/
	black --check src/
