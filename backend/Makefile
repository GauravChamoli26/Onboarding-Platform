# ============================================================================
# Makefile — the commands you actually need
# ----------------------------------------------------------------------------
# Run `make help` to see them. Every target is a one-liner someone can read.
# ============================================================================

.PHONY: help install up down migrate test test-isolation lint format check

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install:  ## Install dependencies including dev extras
	pip install -e ".[dev]"

up:  ## Start local PostgreSQL
	docker compose up -d
	@echo "Waiting for PostgreSQL to accept connections..."
	@until docker compose exec -T postgres pg_isready -U postgres > /dev/null 2>&1; do sleep 1; done
	@echo "PostgreSQL ready on localhost:5432"

down:  ## Stop local PostgreSQL (keeps data)
	docker compose down

migrate:  ## Apply all migrations
	alembic upgrade head

test:  ## Run the full test suite
	pytest -v

test-isolation:  ## Run ONLY the tenant isolation suite (the one that must never fail)
	pytest -v -m integration tests/test_tenant_isolation.py

lint:  ## Check formatting and lint rules
	ruff check src tests
	ruff format --check src tests

format:  ## Auto-fix formatting
	ruff format src tests
	ruff check --fix src tests

check: lint  ## Everything CI runs, locally
	mypy src
	pytest -v
