PYTHON := $(firstword $(wildcard .venv/bin/python) $(wildcard .venv/Scripts/python.exe) python)
VERSION=$(shell grep '^version' pyproject.toml | head -1 | cut -d '"' -f2)
CUSTOMER_NAME_LIST := $(shell grep '^CUSTOMER_NAME_LIST=' .env.etl | cut -d '=' -f2-)

# ---------- Read Azure config from .env.etl ----------
AZURE_ETL_RESOURCE_GROUP_NAME            := $(shell grep '^AZURE_ETL_RESOURCE_GROUP_NAME=' .env.etl | cut -d '=' -f2-)
AZURE_CONTAINER_REGISTRY_NAME                := $(shell grep '^AZURE_CONTAINER_REGISTRY_NAME=' .env.etl | cut -d '=' -f2-)
AZURE_CONTAINER_REGISTRY_LOGIN_SERVER        := $(shell grep '^AZURE_CONTAINER_REGISTRY_LOGIN_SERVER=' .env.etl | cut -d '=' -f2-)
AZURE_RESOURCE_GROUP_LOCATION                := $(shell grep '^AZURE_RESOURCE_GROUP_LOCATION=' .env.etl | cut -d '=' -f2-)
AZURE_CONTAINER_APP_ENV_NAME                := $(shell grep '^AZURE_CONTAINER_APP_ENV_NAME=' .env.etl | cut -d '=' -f2-)
STORAGE_CONN_STR        := $(shell grep '^AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING=' .env.etl | cut -d '=' -f2-)
WEBHOOK_URL             := $(shell grep '^WEBHOOK_URL=' .env.etl | cut -d '=' -f2-)

PROJECT_NAME            := $(shell grep '^name' pyproject.toml | head -1 | cut -d '"' -f2)
AZURE_CONTAINER_APP_IMAGE_NAME               = $(PROJECT_NAME)
JOB_NAME                 = $(PROJECT_NAME)-$(VERSION)
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

provision-infra:
	az containerapp env create \
	  --name $(AZURE_CONTAINER_APP_ENV_NAME) \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) \
	  --location $(AZURE_RESOURCE_GROUP_LOCATION)

provision-dev:
	az containerapp job create \
	  --name $(JOB_NAME)-dev \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) \
	  --environment $(AZURE_CONTAINER_APP_ENV_NAME) \
	  --image $(IMAGE_TAG) \
	  --registry-server $(AZURE_CONTAINER_REGISTRY_LOGIN_SERVER) \
	  --trigger-type Schedule \
	  --cron-expression "0 2 * * *" \
	  --replica-timeout 28800 \
	  --cpu 1 --memory 4Gi \
	  --env-vars \
	    ENV=dev \
	    AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING=secretref:storage-conn-str \
	    AZURE_CONTAINER_STORAGE_NAME=kioskbot-logs \
	    AZURE_CONTAINER_STORAGE_SECRETS_NAME=kioskbot-secrets \
	    CUSTOMER_NAME_LIST="$(CUSTOMER_NAME_LIST)" \
	  --secrets \
	    storage-conn-str="$(STORAGE_CONN_STR)"

provision-prod:
	az containerapp job create \
	  --name $(JOB_NAME)-prod \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) \
	  --environment $(AZURE_CONTAINER_APP_ENV_NAME) \
	  --image $(IMAGE_TAG) \
	  --registry-server $(AZURE_CONTAINER_REGISTRY_LOGIN_SERVER) \
	  --trigger-type Manual \
	  --replica-timeout 28800 \
	  --cpu 1 --memory 4Gi \
	  --env-vars \
	    ENV=prod \
	    AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING=secretref:storage-conn-str \
	    AZURE_CONTAINER_STORAGE_NAME=kioskbot-logs \
	    AZURE_CONTAINER_STORAGE_SECRETS_NAME=kioskbot-secrets \
	    CUSTOMER_NAME_LIST="$(CUSTOMER_NAME_LIST)" \
	  --secrets \
	    storage-conn-str="$(STORAGE_CONN_STR)"

provision: provision-infra provision-dev provision-prod


# ---------- Build & deploy (shared image) ----------

deploy:
	az acr build --registry $(AZURE_CONTAINER_REGISTRY_NAME) --image $(AZURE_CONTAINER_APP_IMAGE_NAME):$(VERSION) .


# ---------- Manual trigger & logs ----------

trigger:
	az containerapp job start \
	  --name $(JOB_NAME)-$(ENV) \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME)

kill:
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

logs:
	az containerapp job logs show \
	  --name $(JOB_NAME)-$(ENV) \
	  --resource-group $(AZURE_ETL_RESOURCE_GROUP_NAME) --follow
