# apps/api/.env supplies the S3_* credentials that compose interpolates for seaweedfs
COMPOSE := docker compose $(if $(wildcard apps/api/.env),--env-file apps/api/.env) -f infrastructure/docker/docker-compose.yml
CHECK := python infrastructure/scripts/check.py

.PHONY: help install db s3 db-down api web check fast check-api check-web up images

help: ## List targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

install: ## Install api and web dependencies
	cd apps/api && uv sync
	cd apps/web && npm install

db: ## Start Postgres + pgvector on :5432
	$(COMPOSE) up -d --wait db

s3: ## Start SeaweedFS S3 object storage on :8333
	$(COMPOSE) up -d --wait seaweedfs

db-down: ## Stop Postgres and SeaweedFS (data volumes kept)
	$(COMPOSE) down

api: ## Run the API with reload on :8000
	cd apps/api && uv run fastapi dev app/main.py

web: ## Run the web dev server on :5173
	cd apps/web && npm run dev

check: ## Full quality gate (needs `make db` for integration tests)
	$(CHECK)

fast: ## Quality gate without integration tests
	$(CHECK) --fast

check-api: ## Quality gate, api only
	$(CHECK) --api

check-web: ## Quality gate, web only
	$(CHECK) --web

up: ## Run the full stack from production images (api :8000, web :8080)
	$(COMPOSE) --profile app up --build

images: ## Build production images locally
	docker build -f infrastructure/docker/api.Dockerfile -t ragidy-api .
	docker build -f infrastructure/docker/web.Dockerfile -t ragidy-web .
