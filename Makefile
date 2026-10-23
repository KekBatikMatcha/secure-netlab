# Lab entry points. Run from the repo root.
#   make up         build and start the lab (waits for the router rules)
#   make down       stop the lab and remove its volumes
#   make test       lint, unit tests, then integration tests against the running lab
#
# Windows without make: run the same commands directly (see README).
# Override the interpreter with: make test PY=.venv/Scripts/python

COMPOSE := docker compose -f compose/docker-compose.yml
PY ?= python

.PHONY: up down lint unit integration test check

# Fetch every device, store changed config versions, and report drift (exit 1 on drift).
check:
	$(PY) -m automation check

up:
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down -v

lint:
	ruff check .

unit:
	$(PY) -m pytest -m "not integration"

integration: up
	$(PY) -m pytest -m integration

test: lint unit integration
