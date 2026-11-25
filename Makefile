# SurgeGate — developer commands.  Run `make help` to list them.
# Usage: make up ENV=dev   (ENV defaults to dev; demo is only for Days 9–12)

ENV        ?= dev
AWS_PROFILE ?= surgegate
AWS_REGION ?= ap-south-1
ENV_DIR    := infra/envs/$(ENV)
PRE_COMMIT ?= pre-commit
K6_SCRIPT  ?= tests/load/k6/sale.js

export AWS_PROFILE AWS_REGION
# The helm provider runs infra/scripts/eks-token.sh with this shell (absolute path: on Windows a
# bare "bash" may resolve to the WSL stub instead of Git Bash/MSYS). cygpath turns the MSYS path
# into one terraform.exe can run; on Linux/macOS (no cygpath) the plain path is used.
BASH_PATH := $(shell command -v bash)
export TF_VAR_token_shell := $(shell cygpath -m '$(BASH_PATH)' 2>/dev/null || echo '$(BASH_PATH)')

# Windows: when MSYS2's GNU make is started from Git Bash (a different MSYS runtime), it gets
# almost none of the Windows environment (USERPROFILE, TEMP, APPDATA, ... are lost), so the AWS
# CLI fails ("Could not determine home directory") and Terraform can't download providers.
# Stop early with the fix. Started from PowerShell or cmd.exe, make gets the full environment.
ifneq ($(wildcard /c/Windows/System32/cmd.exe),)
ifeq ($(strip $(USERPROFILE)),)
$(error make lost the Windows environment (USERPROFILE is empty). From Git Bash run:  cmd //c "make $(MAKECMDGOALS)"  (or run make from PowerShell))
endif
endif

# Every recipe that talks to AWS first checks the CLI works, so a broken environment can never
# look like "nothing found".
AWS_OK = aws sts get-caller-identity --query Account --output text >/dev/null || \
	{ echo "ERROR: the AWS CLI does not work here (credentials expired? run: aws login --profile $(AWS_PROFILE))"; exit 1; }

.DEFAULT_GOAL := help
.PHONY: help init fmt lint test up down load check-env security-off

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

# Hourly-billed layers are switched by Terraform variables:
#   enable_nat_gateway (NAT + EIP) and enable_eks (cluster, nodes, LB controller, Argo CD, ALB).
# Persistent and free/near-free (kept by make down): VPC, subnets, endpoints, ECR, secrets,
# CloudFront (when enabled), state bucket, CI roles.
# Both targets save the plan to a file and apply exactly that file.
UP_PLAN   := $(ENV_DIR)/up.tfplan
DOWN_PLAN := $(ENV_DIR)/down.tfplan
CLUSTER   := surgegate-$(ENV)
TF_LOCK   := -lock-timeout=5m
APPROVE   ?=
DB_ID     := surgegate-$(ENV)-pg
KEEP_SNAPSHOTS ?= 2

# make up restores the newest available final snapshot of the dev database. The lookup must
# SUCCEED: if the AWS call fails, make up stops (it never silently creates an empty database).
# EXPECT_SNAPSHOT=<id> makes it stop unless the newest snapshot is exactly that one.
EXPECT_SNAPSHOT ?=
RESTORE_FILE := $(ENV_DIR)/.restore_snapshot

.PHONY: billing-check

up: check-env ## Create ENV: plan, ask "yes" (or APPROVE=yes), apply, kubeconfig, wait for Argo CD apps
	@$(AWS_OK)
	terraform -chdir=$(ENV_DIR) init -input=false
	@snap=$$(aws rds describe-db-snapshots --db-instance-identifier $(DB_ID) --snapshot-type manual \
		--query 'reverse(sort_by(DBSnapshots[?Status==`available`],&SnapshotCreateTime))[0].DBSnapshotIdentifier' \
		--output text | tr -d '\r') || { echo "ERROR: could not list DB snapshots; stopping (no empty database)."; exit 1; }; \
	[ "$$snap" = "None" ] && snap=""; \
	echo "Restoring the database from snapshot: $${snap:-<none - new empty database>}"; \
	if [ -n "$(EXPECT_SNAPSHOT)" ] && [ "$$snap" != "$(EXPECT_SNAPSHOT)" ]; then \
		echo "STOP: expected snapshot $(EXPECT_SNAPSHOT), found '$$snap'. Nothing created."; exit 1; fi; \
	printf '%s' "$$snap" > $(RESTORE_FILE)
	terraform -chdir=$(ENV_DIR) plan -input=false $(TF_LOCK) -var=enable_nat_gateway=true -var=enable_eks=true \
		-var=enable_data=true -var=enable_kinesis=true -var=restore_snapshot_id=$$(cat $(RESTORE_FILE)) -out=up.tfplan
	@if [ "$(APPROVE)" != "yes" ]; then \
		printf 'Apply this plan? It creates HOURLY-billed resources (NAT, EKS, nodes, ALB, RDS, Redis). Type yes: '; \
		read ans; [ "$$ans" = "yes" ] || { echo "Not applied."; rm -f $(UP_PLAN); exit 1; }; fi
	terraform -chdir=$(ENV_DIR) apply -input=false $(TF_LOCK) up.tfplan
	@rm -f $(UP_PLAN)
	aws eks update-kubeconfig --name $(CLUSTER) --region $(AWS_REGION) --alias $(CLUSTER)
	@echo "Waiting for Argo CD to sync every app from Git (max 10 min)..."
	@for i in $$(seq 1 60); do \
		bad=$$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}={.status.sync.status}/{.status.health.status}{"\n"}{end}' 2>/dev/null | grep -v '=Synced/Healthy' | grep .); \
		[ -z "$$bad" ] && kubectl get applications -n argocd >/dev/null 2>&1 && { echo "All Argo CD apps Synced/Healthy."; break; }; \
		[ $$i -eq 60 ] && { echo "Not healthy yet:"; echo "$$bad"; }; sleep 10; done
	@terraform -chdir=$(ENV_DIR) output

down: check-env ## Remove everything hourly in ENV (EKS, nodes, ALB, NAT, EIP, RDS→final snapshot, Redis); then billing-check
	@# Load balancers made by the LB controller for an Ingress or a LoadBalancer Service are not in
	@# Terraform state; delete those objects first so the controller removes them (none expected:
	@# our ALB is Terraform-owned, ADR 003).
	@if aws eks describe-cluster --name $(CLUSTER) --region $(AWS_REGION) >/dev/null 2>&1; then \
		aws eks update-kubeconfig --name $(CLUSTER) --region $(AWS_REGION) --alias $(CLUSTER) >/dev/null; \
		echo "Deleting Ingresses and LoadBalancer Services (controller-made load balancers)..."; \
		kubectl delete ingress --all --all-namespaces --wait=true --timeout=5m; \
		kubectl get svc -A -o jsonpath='{range .items[?(@.spec.type=="LoadBalancer")]}{.metadata.namespace}{" "}{.metadata.name}{"\n"}{end}' \
			| while read ns n; do [ -n "$$n" ] && kubectl delete svc -n "$$ns" "$$n" --wait=true --timeout=5m; done; \
	fi
	terraform -chdir=$(ENV_DIR) init -input=false
	terraform -chdir=$(ENV_DIR) plan -input=false $(TF_LOCK) -var=enable_nat_gateway=false -var=enable_eks=false \
		-var=enable_data=false -var=enable_kinesis=false -out=down.tfplan
	terraform -chdir=$(ENV_DIR) apply -input=false $(TF_LOCK) down.tfplan
	@rm -f $(DOWN_PLAN)
	@$(MAKE) --no-print-directory prune-snapshots ENV=$(ENV)
	@$(MAKE) --no-print-directory billing-check ENV=$(ENV)

prune-snapshots: check-env ## Keep only the newest KEEP_SNAPSHOTS (default 2) final snapshots of the dev DB
	@$(AWS_OK)
	@set -e; aws rds describe-db-snapshots --db-instance-identifier $(DB_ID) --snapshot-type manual \
		--query 'reverse(sort_by(DBSnapshots[?Status==`available`],&SnapshotCreateTime))[].DBSnapshotIdentifier' \
		--output text | tr '\t' '\n' | tail -n +$$(( $(KEEP_SNAPSHOTS) + 1 )) | while read s; do \
		[ -n "$$s" ] && { echo "Deleting old DB snapshot $$s"; aws rds delete-db-snapshot --db-snapshot-identifier "$$s" >/dev/null; }; done; \
	echo "DB snapshots kept: $$(aws rds describe-db-snapshots --db-instance-identifier $(DB_ID) --snapshot-type manual \
		--query 'DBSnapshots[].DBSnapshotIdentifier' --output text)"

billing-check: check-env ## List everything in ENV that bills by the hour (all lists empty = nothing running)
	@$(AWS_OK)
	@echo "Billing by the hour in $(ENV) (every list should be empty after make down):"
	@set -e; VPC=$$(aws ec2 describe-vpcs --filters Name=tag:Env,Values=$(ENV) Name=tag:Component,Values=network \
		--query 'Vpcs[0].VpcId' --output text); \
	EKS=$$(aws eks list-clusters --query 'clusters[?@==`$(CLUSTER)`]' --output text); \
	EC2=$$(aws ec2 describe-instances --filters Name=vpc-id,Values=$$VPC \
		Name=instance-state-name,Values=pending,running --query 'Reservations[].Instances[].InstanceId' --output text); \
	LB=$$(aws elbv2 describe-load-balancers --query "LoadBalancers[?VpcId=='$$VPC'].LoadBalancerName" --output text); \
	NAT=$$(aws ec2 describe-nat-gateways --filter Name=vpc-id,Values=$$VPC \
		Name=state,Values=pending,available,deleting --query 'NatGateways[].NatGatewayId' --output text); \
	EIP=$$(aws ec2 describe-addresses --query 'Addresses[].PublicIp' --output text); \
	ENI=$$(aws ec2 describe-network-interfaces --filters Name=vpc-id,Values=$$VPC \
		--query 'NetworkInterfaces[?Association.PublicIp].Association.PublicIp' --output text); \
	RDS=$$(aws rds describe-db-instances --query "DBInstances[?DBSubnetGroup.VpcId=='$$VPC'].DBInstanceIdentifier" --output text); \
	REDIS=$$(aws elasticache describe-replication-groups --query 'ReplicationGroups[?starts_with(ReplicationGroupId, `surgegate-$(ENV)`)].ReplicationGroupId' --output text); \
	echo "  EKS clusters:     $$EKS"; \
	echo "  EC2 instances:    $$EC2"; \
	echo "  Load balancers:   $$LB"; \
	echo "  NAT gateways:     $$NAT"; \
	echo "  Elastic IPs:      $$EIP"; \
	echo "  Public IPv4 ENIs: $$ENI"; \
	echo "  RDS instances:    $$RDS"; \
	echo "  ElastiCache:      $$REDIS"; \
	if [ -z "$$EKS$$EC2$$LB$$NAT$$EIP$$ENI$$RDS$$REDIS" ]; then echo "  => nothing billable by the hour is running."; \
	else echo "  => STILL RUNNING: run make down (or check the console)."; fi

load: ## Run a k6 load test (K6_SCRIPT=path)
	@if [ ! -f "$(K6_SCRIPT)" ]; then echo "No k6 script at $(K6_SCRIPT) yet."; \
	else k6 run "$(K6_SCRIPT)"; fi

security-off: ## Turn OFF GuardDuty, Security Hub and the Config recorder (do it before ~26 Dec 2026, when their free trials end); CloudTrail stays
	@$(AWS_OK)
	terraform -chdir=infra/envs/shared init -input=false
	terraform -chdir=infra/envs/shared plan -input=false -var=enable_security_services=false -out=security-off.tfplan
	@if [ "$(APPROVE)" != "yes" ]; then read -p "Apply this plan (removes GuardDuty, Security Hub, Config recorder)? Type yes: " a; [ "$$a" = "yes" ] || { echo "Not applied."; rm -f infra/envs/shared/security-off.tfplan; exit 1; }; fi
	terraform -chdir=infra/envs/shared apply -input=false security-off.tfplan
	@rm -f infra/envs/shared/security-off.tfplan
	@echo "Security services off. Check: aws guardduty list-detectors; aws securityhub describe-hub (should fail: not subscribed)"
