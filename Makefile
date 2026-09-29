.PHONY: install dev test lint fmt coverage seed compose-up compose-down clean

VENV   = .venv
PYTHON = $(VENV)/bin/python
PIP    = uv pip install --python $(PYTHON)

install: ## Create the venv and install dev dependencies
	uv venv $(VENV) --python 3.12
	$(PIP) -r requirements-dev.txt

dev: ## Run the API locally (SQLite, in-memory channels, eager Celery via env)
	$(PYTHON) manage.py migrate
	CELERY_TASK_ALWAYS_EAGER=1 $(PYTHON) manage.py runserver

seed: ## Seed demo data (org, users, accounts, payments, cards)
	CELERY_TASK_ALWAYS_EAGER=1 $(PYTHON) manage.py seed_demo

test: ## Run the test suite
	$(PYTHON) -m pytest

coverage: ## Run tests with coverage report
	$(PYTHON) -m coverage run -m pytest && $(PYTHON) -m coverage report

lint: ## Ruff lint + format check
	$(PYTHON) -m ruff check . && $(PYTHON) -m ruff format --check .

fmt: ## Auto-format with ruff
	$(PYTHON) -m ruff check . --fix && $(PYTHON) -m ruff format .

compose-up: ## Full stack: API + Postgres + Redis + Celery + nginx on :8000
	docker compose up --build -d
	@echo "Swagger UI: http://localhost:8000/api/swagger/"

compose-down: ## Stop and remove the stack (data volume kept)
	docker compose down

clean: ## Remove caches and the dev SQLite database
	rm -rf .pytest_cache .ruff_cache .coverage db.sqlite3 staticfiles htmlcov

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
