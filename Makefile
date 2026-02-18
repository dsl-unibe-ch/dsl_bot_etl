PYTHON := $(firstword $(wildcard .venv/bin/python) $(wildcard .venv/Scripts/python.exe) python)
VERSION=$(shell grep '^version' pyproject.toml | head -1 | cut -d '"' -f2)

lint:
	@echo $@
	$(PYTHON) -m ruff format app demo tests scripts
	@echo $@
	$(PYTHON) -m ruff check --fix app demo tests scripts


etl-pipeline-azure-search-dev:
	@echo $@
	@ENV=dev PYTHONPATH=$(shell pwd) python scripts/rag_data/etl_azure_search.py --customer_name $(customer_name) 

etl-pipeline-azure-search-prod:
	@echo $@
	@ENV=prod PYTHONPATH=$(shell pwd) python scripts/rag_data/etl_azure_search.py --customer_name $(customer_name) 



collect-urls:
	@echo $@
	@TIMESTAMP=$$(date +%s); \
		DATA_DIR=scripts/crawler/data/$(customer_name)/$$TIMESTAMP; \
		mkdir -p $$DATA_DIR; \
		PYTHONPATH=$(shell pwd) scrapy runspider scripts/crawler/unibe_crawler.py -a config=scripts/crawler/configs/$(customer_name).yml -o $$DATA_DIR/url_list.jsonl -s JOBDIR=scripts/crawler/jobs/$(customer_name); \
		if [ ! -s "$$DATA_DIR/url_list.jsonl" ]; then \
			echo "No URLs collected; removing empty directory $$DATA_DIR."; \
			rm -rf "$$DATA_DIR"; \
		fi

extract-content:
	@echo $@	
	@LATEST_DIR=$$(ls -1d scripts/crawler/data/$(customer_name)/[0-9]* 2>/dev/null | awk -F/ '{print $$NF}' | sort -n | tail -1); \
		if [ -z "$$LATEST_DIR" ]; then \
			echo "No timestamped data directory found for customer $(customer_name). Run make collect-urls first."; \
			exit 1; \
		fi; \
		DATA_DIR=scripts/crawler/data/$(customer_name)/$$LATEST_DIR; \
		PYTHONPATH=$(shell pwd) python scripts/crawler/url_content_extractor.py --jsonl_file $$DATA_DIR/url_list.jsonl --customer_name $(customer_name) --output-dir $$DATA_DIR; \
		PYTHONPATH=$(shell pwd) python scripts/crawler/pdf_content_extractor.py --jsonl_file $$DATA_DIR/url_list.jsonl --customer_name $(customer_name) --output_dir $$DATA_DIR --download_dir $$DATA_DIR/raw/pdf_files; \
		ENV=dev PYTHONPATH=$(shell pwd) python scripts/crawler/post_processing.py --customer_name $(customer_name) --data_dir $$DATA_DIR


post-process-content:
	@echo $@	
	@LATEST_DIR=$$(ls -1d scripts/crawler/data/$(customer_name)/[0-9]* 2>/dev/null | awk -F/ '{print $$NF}' | sort -n | tail -1); \
		if [ -z "$$LATEST_DIR" ]; then \
			echo "No timestamped data directory found for customer $(customer_name). Run make collect-urls first."; \
			exit 1; \
		fi; \
		DATA_DIR=scripts/crawler/data/$(customer_name)/$$LATEST_DIR; \
		ENV=dev PYTHONPATH=$(shell pwd) python scripts/crawler/post_processing.py --customer_name $(customer_name) --data_dir $$DATA_DIR


scrape:
	@echo $@
	@rm -rf scripts/crawler/jobs/$(customer_name)
	@make collect-urls customer_name=$(customer_name)
	@make extract-content customer_name=$(customer_name)


copy-secrets-from-container:
	@PYTHONPATH=$(shell pwd) python scripts/copy_secrets_from_container.py --ENV $(ENV)