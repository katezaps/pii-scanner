.PHONY: help install install-cli dev migrate seed purge test lint typecheck db-init db-reset up down

VENV := .venv/bin

help:
	@echo "Targets:"
	@echo "  up           Build and start the full app in Docker"
	@echo "  down         Stop all containers"
	@echo "  install      Install Python + frontend dependencies"
	@echo "  install-cli  Install CLI only (no frontend, no dev deps)"
	@echo "  dev          Run the FastAPI dev server (local)"
	@echo "  migrate      Apply all pending migrations"
	@echo "  seed         Load brokers.json into the database"
	@echo "  test         Run the test suite"
	@echo "  lint         Run ruff"
	@echo "  typecheck    Run mypy"
	@echo "  db-init      Create DB and user if missing, then migrate and seed"
	@echo "  db-reset     Drop, recreate, migrate, and seed the database"

up:
	docker compose up -d --build
	@echo "Waiting for app to be ready..."
	@until docker compose exec -T app python -c "import socket; s=socket.create_connection(('localhost',8000)); s.close()" 2>/dev/null; do sleep 1; done
	docker compose exec app python -m src.db.migrate apply
	docker compose exec app python -m src.db.seed
	@echo ""
	@echo "App is running at http://127.0.0.1:8000"
	@echo "Sign up for an account at http://127.0.0.1:8000/signup"

down:
	docker compose down

install:
	python3 -m venv .venv
	$(VENV)/pip install -e ".[dev]"
	cd frontend && npm install

install-cli:
	python3 -m venv .venv
	$(VENV)/pip install .

dev:
	$(VENV)/uvicorn src.main:app --host 127.0.0.1 --port 8000 --reload

migrate:
	$(VENV)/python -m src.db.migrate apply

seed:
	$(VENV)/python -m src.db.seed

purge:
	$(VENV)/python -m src.db.purge

test:
	$(VENV)/pytest -v

lint:
	$(VENV)/ruff check src tests
	$(VENV)/ruff format --check src tests

typecheck:
	$(VENV)/mypy src

db-init:
	@docker compose up -d postgres
	@echo "Waiting for Postgres to be ready..."
	@until docker compose exec -T postgres pg_isready -U $${POSTGRES_USER:-pii_scanner} > /dev/null 2>&1; do sleep 1; done
	$(MAKE) migrate
	$(MAKE) seed

db-reset:
	docker compose down -v postgres
	docker compose up -d postgres
	@echo "Waiting for Postgres to be ready..."
	@until docker compose exec -T postgres pg_isready -U pii_scanner > /dev/null 2>&1; do sleep 1; done
	$(MAKE) migrate
	$(MAKE) seed
