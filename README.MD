# Kioskbot ETL

ETL pipeline that crawls customer websites, extracts content, enriches it with keywords and questions via Azure OpenAI, and indexes it into Azure AI Search.

## Architecture

```
src/etl_crawler/
├── config.py              # ETLSettings (bootstrap) + AppSettings (app secrets)
├── pipeline.py            # RunContext dataclass + run_pipeline() orchestrator
├── __main__.py            # CLI: python -m src.etl_crawler run --customer quality
├── spiders/
│   └── link_spider.py     # Scrapy CrawlSpider — collects URLs and PDF links
├── steps/
│   ├── crawl.py           # Step 1: run spider → url_list.jsonl
│   ├── extract.py         # Step 2: URL + PDF extraction → content.jsonl
│   ├── post_process.py    # Step 3: enrich via Azure OpenAI → processed_data.xlsx
│   └── index.py           # Step 4: build Azure AI Search index
├── customer_configs/      # Per-customer crawl rules (YAML)
│   ├── quality.yml
│   └── innovation.yml
scripts/
└── copy_secrets_from_container.py   # Download .env files from Azure Blob Storage
tests/
├── test_crawl.py
├── test_extract.py
├── test_post_process.py
├── test_pipeline.py
└── benchmarks/
    └── test_index_quality.py        # Future: RAG quality benchmarks
```

### Pipeline data flow

```
customer.yml ─→ [1. crawl] ─→ url_list.jsonl
                                  │
                              [2. extract] ─→ {customer}_content.jsonl
                                                    │
              .env.{ENV}.app ─→ [3. post_process] ─→ processed_data.xlsx
                                                          │
              .env.{ENV}.app ─→ [4. index] ─→ Azure AI Search Index
```

Each step exposes a `run(ctx: RunContext)` function that receives a shared context (customer name, data directory, YAML config, app settings) and returns a typed result. Steps are independently testable and can be run individually or as a full pipeline.

## Prerequisite

<details>
<summary>Click to expand</summary>

- Python 3.12.11
- Azure CLI (`az login`) for downloading secrets from Azure Blob Storage

</details>

## Configure the Python environment

<details>
<summary>Click to expand</summary>

Install `uv`:

```bash
pip install uv==0.8.14
```

Create virtual environment:

```bash
uv venv .venv --python 3.12.11
```

Activate:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
uv pip install -r pyproject.toml
```

Install pre-commit hooks:

```bash
pre-commit install
```

</details>

## Configure the Environment Variables

<details>
<summary>Click to expand</summary>

There are three levels of environment variables in this project:

1. **`.env.etl`** — Bootstrap settings and Azure infrastructure references. Copy `.env.etl.example` to `.env.etl` and populate:

    | Variable | Description | Where to find it |
    |---|---|---|
    | `AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING` | Connection string for the storage account holding secrets | Azure Portal → Global Resource Group Storage Account|
    | `AZURE_CONTAINER_STORAGE_NAME` | Blob container for logs (`kioskbot-logs`) | Global Resource Group Storage Account Access Keys  |
    | `AZURE_CONTAINER_STORAGE_SECRETS_NAME` | Blob container for secret files (`kioskbot-secrets`) | Global Resource Group Storage Account Access Keys |
    | `CUSTOMER_NAME_LIST` | Space-separated customer names (`quality innovation`) | Matches YAML configs in `customer_configs/` |
    | `AZURE_ETL_RESOURCE_GROUP_NAME` | Resource group for the ETL infrastructure | Azure Portal |
    | `AZURE_CONTAINER_REGISTRY_NAME` | Existing ACR name | Azure Portal → Container registries |
    | `AZURE_CONTAINER_REGISTRY_LOGIN_SERVER` | ACR login server (e.g. `crkbglobal001.azurecr.io`) | Azure Portal → Container registries → Login server |
    | `AZURE_RESOURCE_GROUP_LOCATION` | Azure region (e.g. `switzerlandnorth`) | — |
    | `AZURE_CONTAINER_APP_ENV_NAME` | Container Apps Environment name | Chosen at provision time |
    | `WEBHOOK_URL` | *(Optional)* Microsoft Teams or Slack incoming webhook URL for pipeline notifications. Create one in Teams via **channel settings → Connectors → Incoming Webhook**, copy the URL, and paste it here. Leave empty to skip notifications. | Teams channel settings |

2. **`.env.dev.app`** — App secrets for the dev environment. Downloaded from Azure:

    ```bash
    make copy-secrets-from-container ENV=dev
    ```

3. **`.env.prod.app`** — App secrets for the prod environment. Downloaded from Azure:

    ```bash
    make copy-secrets-from-container ENV=prod
    ```

The bootstrap script (`scripts/copy_secrets_from_container.py`) uses the connection string in `.env.etl` to authenticate with Azure Blob Storage, downloads the `.env.{ENV}` file from the `kioskbot-secrets` container, and saves it locally as `.env.{ENV}.app`.

</details>

## Running the Pipeline Locally

### Full pipeline (all 4 steps)

```bash
make pipeline customer_name=quality ENV=dev
```

This runs: crawl -> extract -> post_process -> index for each customer.

To run the full pipeline for all customers, use

```bash
make pipeline-all-customers ENV=dev
```

### Individual step groups

**Scrape** (crawl + extract):

```bash
make scrape customer_name=quality ENV=dev
```

1. The Scrapy spider follows the rules defined in `src/etl_crawler/customer_configs/quality.yml`, collecting URLs and PDF links into `url_list.jsonl`
2. Each URL is visited with Playwright (expanding accordions/tabs), and PDFs are downloaded and parsed. All content is written to `quality_content.jsonl`

**Post-process only:**

```bash
make post-process customer_name=quality ENV=dev
```

Reads `quality_content.jsonl`, filters short/empty content, generates keywords and example questions via Azure OpenAI, and writes `processed_data.xlsx`.

**Index only:**

```bash
make index customer_name=quality ENV=dev
```

Reads `processed_data.xlsx`, chunks documents with `SemanticChunker`, generates embeddings and titles, creates the Azure AI Search index `kb-quality`, and uploads all chunks.

**Post-process + index together:**

```bash
make etl customer_name=quality ENV=dev
```

### Using the Python CLI directly

```bash
PYTHONPATH=. python -m src.etl_crawler run --customer quality
PYTHONPATH=. python -m src.etl_crawler run --customer quality --steps crawl,extract
PYTHONPATH=. python -m src.etl_crawler run --customer quality --steps post_process,index
PYTHONPATH=. python -m src.etl_crawler run --customer quality --data-dir data/quality/1234567890
```

### Notes

- The crawler config per customer is in `src/etl_crawler/customer_configs/{customer_name}.yml`
- Data artifacts are written to `data/{customer_name}/{timestamp}/` (gitignored)
- Index naming convention: `kb-{customer_name}` (e.g. `kb-quality`, `kb-innovation`)
- The pipeline does not handle scanned PDFs without a text layer

## Running Tests

All tests:

```bash
make test
```

Skip benchmark tests (faster, no Azure required):

```bash
make test-quick
```

## Linting

```bash
make lint
```

## Provisioning and Deployment

The pipeline is deployed to Azure as two **Container Apps Jobs** — one for dev (daily cron) and one for prod (manual trigger after approval). Both use the same Docker image; the `ENV` variable controls which Azure services are targeted.

### Prerequisites

- Azure CLI installed and logged in (`az login`)
- `.env.etl` fully populated (see [Configure the Environment Variables](#configure-the-environment-variables))
- Access to the existing ACR (`crkbglobal001` in `rg-kb-global-001`)

### One-time infrastructure setup

Provision the Container Apps Environment and both jobs:

```bash
make provision
```

This runs three sub-targets in order:

- `make provision-infra` — creates the Container Apps Environment
- `make provision-dev` — creates the dev job with a daily cron schedule (`0 2 * * *`)
- `make provision-prod` — creates the prod job with manual trigger only

Job names are derived from `pyproject.toml` (e.g. `kioskbot-etl-0.1.0-dev`, `kioskbot-etl-0.1.0-prod`).

### Build and deploy the image

Build the Docker image in Azure and push it to ACR:

```bash
make deploy
```

The image is tagged as `{ACR_LOGIN_SERVER}/{PROJECT_NAME}:{VERSION}` (e.g. `crkbglobal001.azurecr.io/kioskbot-etl:0.1.0`). Run this after every code change that should be picked up by the scheduled jobs.

### Daily workflow

1. **02:00 UTC** — the dev job starts automatically
2. The container runs `make run-scheduled`, which chains:
   - `copy-secrets-from-container` — downloads `.env.dev.app` from Blob Storage
   - `pipeline-all-customers` — runs the full pipeline for every customer
   - `smoke-test` — validates each AI Search index has documents and returns search results
   - `notify` — sends a webhook notification to Teams/Slack
3. **Review** the dev results (chatbot, logs, notification)
4. **Trigger prod** when satisfied:

    ```bash
    make trigger ENV=prod
    ```

5. The prod job runs the same flow against prod Azure services

### Useful commands

| Command | Description |
|---|---|
| `make provision` | One-time: create Container Apps Environment + dev/prod jobs |
| `make deploy` | Build and push Docker image to ACR |
| `make trigger ENV=dev` | Manually start the dev job (outside cron schedule) |
| `make trigger ENV=prod` | Manually start the prod job (after reviewing dev) |
| `make kill ENV=dev` | Stop all currently running dev job executions |
| `make kill ENV=prod` | Stop all currently running prod job executions |
| `make logs ENV=dev` | Tail the dev job logs |
| `make logs ENV=prod` | Tail the prod job logs |
| `make smoke-test ENV=dev` | Run smoke tests locally against dev indexes |
