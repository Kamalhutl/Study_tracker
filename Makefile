.DEFAULT_GOAL := help
PYTHON ?= python3.12
VENV ?= .venv
BIN := $(VENV)/bin
export DJANGO_SETTINGS_MODULE ?= config.settings.dev
export PATH := $(BIN):$(PATH)

ifneq (,$(wildcard .env))
include .env
export
endif

.PHONY: help install up down logs sh migrate makemigrations superuser test-coverage test lint fmt typecheck schema check

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install:  ## Create venv and install dev requirements
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements/dev.txt

up:  ## docker compose up (db, redis, web, worker, beat)
	docker compose up --build

down:  ## Stop and remove containers
	docker compose down

logs:  ## Tail all service logs
	docker compose logs -f

sh:  ## Shell into the web container
	docker compose exec web bash

migrate:  ## Apply migrations
	python manage.py migrate

makemigrations:  ## Create migrations
	python manage.py makemigrations

superuser:  ## Create a superuser (non-interactive when DJANGO_SUPERUSER_EMAIL is set)
	@if [ -n "$$DJANGO_SUPERUSER_EMAIL" ]; then \
		python manage.py createsuperuser --noinput; \
	else \
		python manage.py createsuperuser; \
	fi

test:  ## Run pytest with coverage
	DJANGO_SETTINGS_MODULE=config.settings.test $(BIN)/pytest --cov --cov-fail-under=85

lint:  ## ruff check
	$(BIN)/ruff check .

fmt:  ## black format (write) + ruff format
	$(BIN)/black . && $(BIN)/ruff check . --fix && $(BIN)/ruff format .

typecheck:  ## mypy strict on our code
	$(BIN)/mypy --config-file pyproject.toml .

schema:  ## Dump OpenAPI schema to docs/openapi.yaml
	python manage.py spectacular --file docs/openapi.yaml --color

seed-demo:  ## Seed deterministic demo companies/jobs (DEBUG only)
	python manage.py seed_demo

companies-due:  ## List companies due for scraping
	python manage.py companies_due

rebuild-search-vectors:  ## Rebuild Job search vectors
	python manage.py rebuild_search_vectors

check: lint fmt typecheck test  ## Everything before a commit