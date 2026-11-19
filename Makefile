# SurgeGate — developer commands.  Run `make help` to list them.
# Usage: make up ENV=dev   (ENV defaults to dev; demo is only for Days 9–12)

ENV        ?= dev
AWS_PROFILE ?= surgegate
AWS_REGION ?= ap-south-1
ENV_DIR    := infra/envs/$(ENV)
PRE_COMMIT ?= pre-commit
K6_SCRIPT  ?= tests/load/k6/sale.js

export AWS_PROFILE AWS_REGION

.DEFAULT_GOAL := help
.PHONY: help init fmt lint test up down load check-env

help: ## List available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

init: ## One-time setup: install git hooks and the tflint AWS plugin
	$(PRE_COMMIT) install
	tflint --init --config=.tflint.hcl

fmt: ## Format Terraform and Python code
	terraform fmt -recursive infra
	ruff format .

lint: ## Run every pre-commit hook on every file
	$(PRE_COMMIT) run --all-files

test: ## Run unit tests for each Python service that has tests
	@found=0; for d in services/*/; do \
		if [ -d "$$d/tests" ]; then found=1; echo "== $$d"; (cd "$$d" && python -m pytest -q) || exit 1; fi; \
	done; [ $$found -eq 1 ] || echo "No service tests yet."

check-env:
	@case "$(ENV)" in dev|demo) ;; *) echo "ENV must be dev or demo (got '$(ENV)')"; exit 1;; esac

# up/down are completed on Day 2 ("make up / make down working for dev").
# Until then they refuse to pretend: no .tf files means nothing exists to create or destroy.
up: check-env ## Create the ENV environment (asks before applying)
	@if ! ls $(ENV_DIR)/*.tf >/dev/null 2>&1; then \
		echo "No Terraform in $(ENV_DIR) yet — nothing to create."; exit 0; fi; \
	echo "make up is not wired yet (Day 2 task). Run terraform plan/apply by hand."; exit 1

down: check-env ## Destroy the hourly-billed parts of ENV
	@if ! ls $(ENV_DIR)/*.tf >/dev/null 2>&1; then \
		echo "No Terraform in $(ENV_DIR) yet — nothing to destroy."; exit 0; fi; \
	echo "make down is not wired yet (Day 2 task). CHECK THE CONSOLE for running resources."; exit 1

load: ## Run a k6 load test (K6_SCRIPT=path)
	@if [ ! -f "$(K6_SCRIPT)" ]; then echo "No k6 script at $(K6_SCRIPT) yet."; \
	else k6 run "$(K6_SCRIPT)"; fi
