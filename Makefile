PYTHON := $(firstword $(wildcard .venv/bin/python) $(wildcard .venv/Scripts/python.exe) python)
VERSION=$(shell grep '^version' pyproject.toml | head -1 | cut -d '"' -f2)
CUSTOMER_NAME_LIST := $(shell grep '^CUSTOMER_NAME_LIST=' .env.etl | cut -d '=' -f2-)
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
