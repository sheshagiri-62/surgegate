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

# Hourly-billed layers are switched by variables: NAT (network) and EKS (cluster, nodes, LB controller).
# Both targets save the plan to a file and apply exactly that file. Day 2 Task 5 adds the
# ingress clean-up step (ALBs created by the controller) before the EKS switch-off.
UP_PLAN   := $(ENV_DIR)/up.tfplan
DOWN_PLAN := $(ENV_DIR)/down.tfplan
CLUSTER   := surgegate-$(ENV)

up: check-env ## Create the ENV environment: shows the plan, asks "yes" before applying
	terraform -chdir=$(ENV_DIR) init -input=false
	terraform -chdir=$(ENV_DIR) plan -input=false -var=enable_nat_gateway=true -var=enable_eks=true -out=up.tfplan
	@printf 'Apply this plan? It creates HOURLY-billed resources (NAT, EKS, nodes). Type yes: '; \
		read ans; [ "$$ans" = "yes" ] || { echo "Not applied."; rm -f $(UP_PLAN); exit 1; }
	terraform -chdir=$(ENV_DIR) apply -input=false up.tfplan
	@rm -f $(UP_PLAN)
	aws eks update-kubeconfig --name $(CLUSTER) --region $(AWS_REGION)

down: check-env ## Remove the hourly-billed parts of ENV (EKS + nodes, NAT + Elastic IP); free VPC stays
	terraform -chdir=$(ENV_DIR) init -input=false
	terraform -chdir=$(ENV_DIR) plan -input=false -var=enable_nat_gateway=false -var=enable_eks=false -out=down.tfplan
	terraform -chdir=$(ENV_DIR) apply -input=false down.tfplan
	@rm -f $(DOWN_PLAN)
	@echo "Still billing by the hour in $(ENV) (every list below should be empty):"
	@printf '  EKS clusters:   '; aws eks list-clusters --query 'clusters[?@==`$(CLUSTER)`]' --output text; echo
	@printf '  EC2 instances:  '; aws ec2 describe-instances --filters Name=tag:eks:cluster-name,Values=$(CLUSTER) \
		Name=instance-state-name,Values=pending,running --query 'Reservations[].Instances[].InstanceId' --output text; echo
	@printf '  Load balancers: '; aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName' --output text; echo
	@printf '  NAT gateways:   '; aws ec2 describe-nat-gateways --filter Name=tag:Env,Values=$(ENV) \
		Name=state,Values=pending,available --query 'NatGateways[].NatGatewayId' --output text; echo
	@printf '  Elastic IPs:    '; aws ec2 describe-addresses --filters Name=tag:Env,Values=$(ENV) \
		--query 'Addresses[].PublicIp' --output text; echo

load: ## Run a k6 load test (K6_SCRIPT=path)
	@if [ ! -f "$(K6_SCRIPT)" ]; then echo "No k6 script at $(K6_SCRIPT) yet."; \
	else k6 run "$(K6_SCRIPT)"; fi
