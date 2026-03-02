PYTHON := $(firstword $(wildcard .venv/bin/python) $(wildcard .venv/Scripts/python.exe) python)
VERSION=$(shell grep '^version' pyproject.toml | head -1 | cut -d '"' -f2)
CUSTOMER_NAME_LIST ?= $(shell [ -f .env.etl ] && grep '^CUSTOMER_NAME_LIST=' .env.etl | cut -d '=' -f2-)

# ---------- Read Azure config from .env.etl ----------
AZURE_ETL_RESOURCE_GROUP_NAME ?= $(shell [ -f .env.etl ] && grep '^AZURE_ETL_RESOURCE_GROUP_NAME=' .env.etl | cut -d '=' -f2-)
AZURE_CONTAINER_REGISTRY_NAME ?= $(shell [ -f .env.etl ] && grep '^AZURE_CONTAINER_REGISTRY_NAME=' .env.etl | cut -d '=' -f2-)
AZURE_CONTAINER_REGISTRY_LOGIN_SERVER ?= $(shell [ -f .env.etl ] && grep '^AZURE_CONTAINER_REGISTRY_LOGIN_SERVER=' .env.etl | cut -d '=' -f2-)
AZURE_RESOURCE_GROUP_LOCATION ?= $(shell [ -f .env.etl ] && grep '^AZURE_RESOURCE_GROUP_LOCATION=' .env.etl | cut -d '=' -f2-)
AZURE_CONTAINER_APP_ENV_NAME ?= $(shell [ -f .env.etl ] && grep '^AZURE_CONTAINER_APP_ENV_NAME=' .env.etl | cut -d '=' -f2-)
AZURE_LOG_ANALYTICS_WORKSPACE_NAME ?= $(shell [ -f .env.etl ] && grep '^AZURE_LOG_ANALYTICS_WORKSPACE_NAME=' .env.etl | cut -d '=' -f2-)
STORAGE_CONN_STR ?= $(shell [ -f .env.etl ] && grep '^AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING=' .env.etl | cut -d '=' -f2-)
WEBHOOK_URL ?= $(shell [ -f .env.etl ] && grep '^WEBHOOK_URL=' .env.etl | cut -d '=' -f2-)

PROJECT_NAME            := $(shell grep '^name' pyproject.toml | head -1 | cut -d '"' -f2)
AZURE_CONTAINER_APP_IMAGE_NAME               = $(PROJECT_NAME)
PROJECT_NAME_SAFE       := $(shell echo "$(PROJECT_NAME)" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9-]+/-/g; s/--+/-/g; s/^-+//; s/-+$$//')
VERSION_SAFE            := $(shell echo "$(VERSION)" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9-]+/-/g; s/--+/-/g; s/^-+//; s/-+$$//')
# Azure Container Apps job names must be <32 chars. Reserve room for "-prod" suffix.
JOB_NAME                := $(shell echo "$(PROJECT_NAME_SAFE)-$(VERSION_SAFE)" | cut -c1-26 | sed -E 's/-+$$//')
REPLICA_RETRY_LIMIT      = 1
PARALLELISM              = 1
REPLICA_COMPLETION_COUNT = 1
IMAGE_TAG                = $(AZURE_CONTAINER_REGISTRY_LOGIN_SERVER)/$(AZURE_CONTAINER_APP_IMAGE_NAME):$(VERSION)

lint:
	@echo $@
	$(PYTHON) -m ruff format src tests scripts
	@echo $@
	$(PYTHON) -m ruff check --fix src tests scripts


# ---------- Full pipeline (all steps) ----------

pipeline-all-customers:
	@echo $@
	@for customer in $(CUSTOMER_NAME_LIST); do \
		ENV=$(ENV) PYTHONPATH=$(shell pwd) $(PYTHON) -m src.etl_crawler run \
			--customer $$customer; \
	done

pipeline:
	@echo $@
	@ENV=$(ENV) PYTHONPATH=$(shell pwd) $(PYTHON) -m src.etl_crawler run \
		--customer $(customer_name)


# ---------- Individual step groups ----------

scrape:
	@echo $@
	@ENV=$(ENV) PYTHONPATH=$(shell pwd) $(PYTHON) -m src.etl_crawler run \
		--customer $(customer_name) --steps crawl,extract

post-process:
	@echo $@
	@ENV=$(ENV) PYTHONPATH=$(shell pwd) $(PYTHON) -m src.etl_crawler run \
		--customer $(customer_name) --steps post_process

index:
	@echo $@
	@ENV=$(ENV) PYTHONPATH=$(shell pwd) $(PYTHON) -m src.etl_crawler run \
		--customer $(customer_name) --steps index

etl:
	@echo $@
	@ENV=$(ENV) PYTHONPATH=$(shell pwd) $(PYTHON) -m src.etl_crawler run \
		--customer $(customer_name) --steps post_process,index


# ---------- Tests ----------

test:
	@echo $@
	@PYTHONPATH=$(shell pwd) $(PYTHON) -m pytest tests/ -v

test-quick:
	@echo $@
	@PYTHONPATH=$(shell pwd) $(PYTHON) -m pytest tests/ -v --ignore=tests/benchmarks


# ---------- Bootstrap ----------

copy-secrets-from-container:
	@PYTHONPATH=$(shell pwd) $(PYTHON) scripts/copy_secrets_from_container.py --ENV $(ENV)


# ---------- Container entrypoint (runs inside Docker) ----------

run-scheduled:
	@$(MAKE) copy-secrets-from-container ENV=$(ENV)
	@$(MAKE) pipeline-all-customers ENV=$(ENV)
	@$(MAKE) smoke-test ENV=$(ENV)
	@$(MAKE) notify ENV=$(ENV)

smoke-test:
	@PYTHONPATH=$(shell pwd) $(PYTHON) scripts/smoke_test.py --ENV $(ENV)

notify:
	@curl -sf -X POST -H "Content-Type: application/json" \
	  -d '{"text":"ETL pipeline ($(ENV)) finished. Smoke tests passed. Trigger prod: make trigger ENV=prod"}' \
	  "$(WEBHOOK_URL)" || echo "Webhook notification skipped (no WEBHOOK_URL)"


# ---------- Provision infrastructure ----------

require-acr-creds:
	@test -n "$(ACR_USERNAME)" || (echo "Error: ACR_USERNAME is required."; echo "Usage: make provision-dev ACR_USERNAME='<acr-user>' ACR_PASSWORD='<acr-pass>'"; exit 1)
	@test -n "$(ACR_PASSWORD)" || (echo "Error: ACR_PASSWORD is required."; echo "Usage: make provision-dev ACR_USERNAME='<acr-user>' ACR_PASSWORD='<acr-pass>'"; exit 1)

require-env:
	@test -n "$(ENV)" || (echo "Error: ENV is required (dev or prod). Usage: make logs ENV=dev"; exit 1)
	@test "$(ENV)" = "dev" -o "$(ENV)" = "prod" || (echo "Error: ENV must be 'dev' or 'prod'."; exit 1)

require-prod-approval:
	@if [ "$(ENV)" = "prod" ] && [ "$(PROD_APPROVED)" != "YES" ]; then \
	  echo "Refusing to trigger prod without explicit approval."; \
	  echo "Use: make trigger ENV=prod PROD_APPROVED=YES"; \
	  exit 1; \
	fi

require-image-in-acr:
	@tag_exists=$$(az acr repository show-tags \
	  --name $(AZURE_CONTAINER_REGISTRY_NAME) \
	  --repository $(AZURE_CONTAINER_APP_IMAGE_NAME) \
	  --query "[?@=='$(VERSION)'] | length(@)" -o tsv); \
	test "$$tag_exists" != "0" || (echo "Error: image tag $(VERSION) not found in ACR."; echo "Run: make docker-build-image && make docker-push-image ACR_USERNAME='...' ACR_PASSWORD='...'"; exit 1)

provision-rg:
	az group create \
	  --name $(AZURE_ETL_RESOURCE_GROUP_NAME) \
	  --location $(AZURE_RESOURCE_GROUP_LOCATION)

provision-infra:
	az monitor log-analytics workspace create \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) \
	  --workspace-name $(AZURE_LOG_ANALYTICS_WORKSPACE_NAME) \
	  --location $(AZURE_RESOURCE_GROUP_LOCATION)
	az containerapp env create \
	  --name $(AZURE_CONTAINER_APP_ENV_NAME) \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) \
	  --location $(AZURE_RESOURCE_GROUP_LOCATION) \
	  --logs-workspace-id "$$(az monitor log-analytics workspace show --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) --workspace-name $(AZURE_LOG_ANALYTICS_WORKSPACE_NAME) --query customerId -o tsv)" \
	  --logs-workspace-key "$$(az monitor log-analytics workspace get-shared-keys --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) --workspace-name $(AZURE_LOG_ANALYTICS_WORKSPACE_NAME) --query primarySharedKey -o tsv)"

provision-job: require-acr-creds require-image-in-acr require-env
	@trigger_type=Manual; \
	cron_args=""; \
	if [ "$(ENV)" = "dev" ]; then \
	  trigger_type=Schedule; \
	  cron_args='--cron-expression "0 2 * * *"'; \
	fi; \
	eval "az containerapp job create \
	  --name $(JOB_NAME)-$(ENV) \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) \
	  --environment $(AZURE_CONTAINER_APP_ENV_NAME) \
	  --image $(IMAGE_TAG) \
	  --registry-server $(AZURE_CONTAINER_REGISTRY_LOGIN_SERVER) \
	  --registry-username \"$(ACR_USERNAME)\" \
	  --registry-password \"$(ACR_PASSWORD)\" \
	  --trigger-type $$trigger_type \
	  $$cron_args \
	  --parallelism $(PARALLELISM) \
	  --replica-completion-count $(REPLICA_COMPLETION_COUNT) \
	  --replica-timeout 28800 \
	  --replica-retry-limit $(REPLICA_RETRY_LIMIT) \
	  --cpu 2 --memory 4Gi \
	  --env-vars \
	    ENV=$(ENV) \
	    AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING=secretref:storage-conn-str \
	    AZURE_CONTAINER_STORAGE_NAME=kioskbot-logs \
	    AZURE_CONTAINER_STORAGE_SECRETS_NAME=kioskbot-secrets \
	    AZURE_ETL_RESOURCE_GROUP_NAME=\"$(AZURE_ETL_RESOURCE_GROUP_NAME)\" \
	    AZURE_CONTAINER_REGISTRY_NAME=\"$(AZURE_CONTAINER_REGISTRY_NAME)\" \
	    AZURE_CONTAINER_REGISTRY_LOGIN_SERVER=\"$(AZURE_CONTAINER_REGISTRY_LOGIN_SERVER)\" \
	    AZURE_RESOURCE_GROUP_LOCATION=\"$(AZURE_RESOURCE_GROUP_LOCATION)\" \
	    AZURE_CONTAINER_APP_ENV_NAME=\"$(AZURE_CONTAINER_APP_ENV_NAME)\" \
	    AZURE_LOG_ANALYTICS_WORKSPACE_NAME=\"$(AZURE_LOG_ANALYTICS_WORKSPACE_NAME)\" \
	    WEBHOOK_URL=\"$(WEBHOOK_URL)\" \
	    CUSTOMER_NAME_LIST=\"$(CUSTOMER_NAME_LIST)\" \
	  --secrets \
	    storage-conn-str=\"$(STORAGE_CONN_STR)\""

provision-dev: require-acr-creds require-image-in-acr
	@$(MAKE) provision-job ENV=dev ACR_USERNAME="$(ACR_USERNAME)" ACR_PASSWORD="$(ACR_PASSWORD)"

provision-prod: require-acr-creds require-image-in-acr
	@$(MAKE) provision-job ENV=prod ACR_USERNAME="$(ACR_USERNAME)" ACR_PASSWORD="$(ACR_PASSWORD)"

# ---------- Build & push (shared image) ----------

docker-build-image:
	docker build -t $(AZURE_CONTAINER_APP_IMAGE_NAME):$(VERSION) .

docker-push-image: require-acr-creds
	docker tag $(AZURE_CONTAINER_APP_IMAGE_NAME):$(VERSION) $(IMAGE_TAG)
	echo "$(ACR_PASSWORD)" | docker login $(AZURE_CONTAINER_REGISTRY_LOGIN_SERVER) --username "$(ACR_USERNAME)" --password-stdin
	docker push $(IMAGE_TAG)


# ---------- Manual trigger & logs ----------

jobs-list:
	az containerapp job list \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) \
	  -o table

job-name: require-env
	@echo $(JOB_NAME)-$(ENV)

job-show: require-env
	az containerapp job show \
	  --name $(JOB_NAME)-$(ENV) \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME)

job-trigger: require-env
	az containerapp job show \
	  --name $(JOB_NAME)-$(ENV) \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) \
	  --query "properties.configuration.triggerType" -o tsv

job-cron: require-env
	az containerapp job show \
	  --name $(JOB_NAME)-$(ENV) \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) \
	  --query "properties.configuration.scheduleTriggerConfig.cronExpression" -o tsv

trigger: require-env require-prod-approval
	az containerapp job start \
	  --name $(JOB_NAME)-$(ENV) \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME)

trigger-dev:
	@$(MAKE) trigger ENV=dev

trigger-prod:
	@$(MAKE) trigger ENV=prod PROD_APPROVED=YES

kill: require-env
	@job_name="$(JOB_NAME)-$(ENV)"; \
	executions=$$(az containerapp job execution list \
	  --name $$job_name \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) \
	  --query "[?properties.status=='Running'].name" -o tsv); \
	if [ -z "$$executions" ]; then \
	  echo "No running executions for $$job_name."; \
	else \
	  for execution in $$executions; do \
	    echo "Stopping execution $$execution for $$job_name..."; \
	    az containerapp job execution stop \
	      --name $$execution \
	      --job-name $$job_name \
	      --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME); \
	  done; \
	fi

logs: require-env
	az containerapp job logs show \
	  --name $(JOB_NAME)-$(ENV) \
	  --container $(JOB_NAME)-$(ENV) \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) --follow


# ---------- Destroy provisioned resources ----------

require-destroy-confirm:
	@test "$(DESTROY_CONFIRM)" = "YES" || (echo "Refusing to destroy resources. Re-run with DESTROY_CONFIRM=YES"; exit 1)

destroy-job: require-destroy-confirm require-env
	az containerapp job delete \
	  --name $(JOB_NAME)-$(ENV) \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) \
	  --yes

destroy-infra: require-destroy-confirm
	-az containerapp env delete \
	  --name $(AZURE_CONTAINER_APP_ENV_NAME) \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) \
	  --yes
	-az monitor log-analytics workspace delete \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) \
	  --workspace-name $(AZURE_LOG_ANALYTICS_WORKSPACE_NAME) \
	  --yes

