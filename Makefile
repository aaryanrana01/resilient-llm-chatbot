# One-command local stack: backend on :8000, frontend on :3000.
.DEFAULT_GOAL := help
COMPOSE ?= docker compose
PYTHON ?= python3
API ?= http://localhost:8000

.PHONY: help up down logs ps restart clean test test-backend test-frontend dev-backend dev-frontend smoke

help: ## show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

.env:
	@cp .env.example .env
	@echo ">> Created .env from .env.example - put your real LLM_API_KEYS in it."

up: .env ## build and start backend + frontend (http://localhost:3000)
	$(COMPOSE) up -d --build
	@echo ""
	@echo "  frontend: http://localhost:3000"
	@echo "  backend:  http://localhost:8000/health"

down: ## stop the stack (the SQLite volume is kept)
	$(COMPOSE) down

logs: ## follow logs of both services
	$(COMPOSE) logs -f

ps: ## show container status
	$(COMPOSE) ps

restart: down up ## restart the stack

clean: ## stop the stack AND delete the SQLite volume
	$(COMPOSE) down -v

test: test-backend test-frontend ## run all tests

test-backend: ## run backend tests (needs Python 3.12+)
	cd backend && $(PYTHON) -m pip install -q -r requirements-dev.txt && $(PYTHON) -m pytest

test-frontend: ## run frontend tests
	cd frontend && npm ci --no-audit --no-fund && npm test

dev-backend: ## run the backend without Docker on :8000
	cd backend && set -a && . ../.env && set +a && DATABASE_URL=sqlite:///./data/app.db uvicorn app.main:app --reload --port 8000

dev-frontend: ## run the frontend dev server without Docker on :3000
	cd frontend && npm run dev

smoke: ## check a running backend against the API contract: make smoke API=https://your-backend
	./scripts/smoke_test.sh $(API)
