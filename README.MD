# DSL Bot ETL

This repository contains the code for ETL pipeline of the DSL Bot Project that crawls customer websites, extracts content, enriches it with keywords and questions via Azure OpenAI, and indexes it into Azure AI Search as a scheduled job inside an Azure container.


## Architecture


```mermaid
flowchart TD
  subgraph daily [Daily Cron - 2:00 AM UTC]
    DevTrigger["Daily cron 2:00 AM UTC (dev)"]
    DevJob["Container Apps Job"]
    DevTrigger --> DevJob
  end

  DevJob -->|1| Secrets["Download env"]
  Secrets -->|2| Pipeline["Run pipeline-all"]

  subgraph etlPipeline [Pipeline Stages]
    Crawl["1 crawl"]
    Extract["2 extract"]
    LocalDocs["3 local docs (optional)"]
    PostProcess["4 post process"]
    Index["5 create index"]
    Crawl --> Extract --> LocalDocs --> PostProcess --> Index
  end

  Pipeline --> Crawl
  Index -->|3| SmokeTest["Smoke test AI Search"]
  SmokeTest -->|4| Notify["Notification (Optional)"]
  Notify -.->|5 manual approval| Operator["Operator reviews dev"]
  Operator -.->|"make trigger ENV=prod PROD_APPROVED=YES"| ProdJob["Trigger prod manual"]
  ProdJob --> ProdPipeline["Same steps in Prod"]

  subgraph shared [Shared Infrastructure]
    ACR["ACR global"]
    BlobStorage["Blob Storage"]
  end

  ACR -.->|image| DevJob
  ACR -.->|image| ProdJob
```

The infrastructure is the same for both dev and prod environments. However the respective `env` file is applied during the provisioning of the job for `dev` and `prod` respectively. 

The job for `dev` is triggered daily at the specified time. Within the job, the smoke tests are performed. 
The smoke tests results are viewable inside the logs. In the future, further evaluation steps will be added. If the results are satisfactory, the `prod` job can be manually triggered. The separation of `dev` and `prod` jobs is done to ensure quality of the index created to minimise the disruption.  


## Project Structure
<details>
<summary>Click to expand</summary>

```
src/etl_crawler/
├── config.py              # ETLSettings (bootstrap) + AppSettings (app secrets)
├── pipeline.py            # RunContext dataclass + run_pipeline() orchestrator
├── __main__.py            # CLI: python -m src.etl_crawler run --customer bnf
├── spiders/
│   └── link_spider.py     # Scrapy CrawlSpider — collects URLs and PDF links
├── steps/
│   ├── crawl.py           # Step 1: run spider → url_list.jsonl
│   ├── extract.py         # Step 2: URL + PDF extraction → content.jsonl
│   ├── local_docs.py      # Step 3 (optional): ingest local PDFs/text files → content.jsonl
│   ├── post_process.py    # Step 4: enrich via Azure OpenAI → processed_data.xlsx
│   └── index.py           # Step 5: build Azure AI Search index
├── customer_configs/      # Per-customer crawl rules (YAML)
│   ├── customerA.yml
│   └── customerB.yml
scripts/
└── copy_secrets_from_container.py   # Download .env files from Azure Blob Storage
└── smoke_test.py   # Validate AI Search indexes are healthy.
tests/
├── test_crawl.py
├── test_extract.py
├── test_post_process.py
├── test_index.py
├── test_pipeline.py
└── benchmarks/
    └── test_index_quality.py        # Future: RAG quality benchmarks
```

Each step exposes a `run(run_context: RunContext)` function that receives a shared context (customer name, data directory, YAML config, app settings) and returns a typed result. Steps are independently testable and can be run individually or as a full pipeline.
</details>

## Prerequisite

<details>
<summary>Click to expand</summary>

- Python 3.14.7
- Azure CLI (`az login`) for downloading secrets from Azure Blob Storage

</details>

## Configure the Python environment

<details>
<summary>Click to expand</summary>

Install `uv`:

```bash
pip install uv==0.12.9
```

Create virtual environment:

```bash
uv venv .venv --python 3.14.7
```

Activate:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
uv pip install -r pyproject.toml
```

Download the Playwright browser binary used by the extract step (required once per machine; a fresh `uv` venv or a Playwright version bump does not include it):

```bash
make playwright-install
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
    | `AZURE_CONTAINER_STORAGE_NAME` | Blob container for logs (`dsl-bot-logs`) | Global Resource Group Storage Account Access Keys  |
    | `AZURE_CONTAINER_STORAGE_SECRETS_NAME` | Blob container for secret files (`dsl-bot-secrets`) | Global Resource Group Storage Account Access Keys |
    | `AZURE_CONTAINER_STORAGE_ETL_FILES_NAME` | Blob container for ETL outputs and intermediate files (`dsl-bot-etl-files`) | Global Resource Group Storage Account Access Keys |
    | `AZURE_CUSTOMER_REGISTRY_ACCOUNT_URL` | Blob endpoint of the storage account hosting the customer registry (informational; same account as above) | Azure Portal → Storage account → Endpoints |
    | `AZURE_CUSTOMER_REGISTRY_MANIFEST_CONTAINER` | Container holding the `customers.json` manifest (`customer-registry`) | See [Customer Registry](#customer-registry) |
    | `AZURE_CUSTOMER_REGISTRY_CONTAINER_PREFIX` | Prefix + customer_id = the per-customer registry container name (`customer-registry-`) | See [Customer Registry](#customer-registry) |
    | `AZURE_ETL_RESOURCE_GROUP_NAME` | Resource group for the ETL infrastructure | Azure Portal |
    | `AZURE_CONTAINER_REGISTRY_NAME` | Existing ACR name | Azure Portal → Container registries |
    | `AZURE_CONTAINER_REGISTRY_LOGIN_SERVER` | ACR login server (e.g. `crdbglobal001.azurecr.io`) | Azure Portal → Container registries → Login server |
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

The bootstrap script (`scripts/copy_secrets_from_container.py`) uses the connection string in `.env.etl` to authenticate with Azure Blob Storage, downloads the `.env.{ENV}` file from the `dsl-bot-secrets` container, and saves it locally as `.env.{ENV}.app`.

</details>

## Customer Registry

<details>
<summary>Click to expand</summary>

Customers are discovered from a registry ( either stored in Azure Blob Storage or locally (test purposes))

- `AZURE_CUSTOMER_REGISTRY_MANIFEST_CONTAINER` is the `customer-registry`) which holds `customers.json` defining the customers
      ```json
      {"customer_ids": ["bnf", "default"]}
      ```
- `AZURE_CUSTOMER_REGISTRY_CONTAINER_PREFIX}{customer_id}`, e.g. `customer-registry-bnf`) holds:
  - `config.env` — a dotenv file owned and uploaded by the backend repo. The ETL only reads `CUSTOMER_ID`, `CUSTOMER_ROOT_URLS` (a JSON array string, e.g. `["https://example.com"]`), `SEARCH_INDEX_NAME`, and `ETL_ENABLED`; all other keys are ignored.
  - `crawl_config.yml` — the production crawl rules (same shape as the local YAMLs in `customer_configs/`

`SEARCH_INDEX_NAME` is the Azure AI Search index name for the customer.

Only customers with `ETL_ENABLED=True` are processed by `make pipeline-all-customers` / `python -m src.etl_crawler run-all`. A malformed manifest or a malformed customer `config.env` fails the whole run immediately (no local fallback); a customer with `ETL_ENABLED=False` is simply skipped.

### Onboarding a new customer

1. Register the customer via the **backend repo** (`dsl_bot_backend`, see its README) — this creates the registry container's `config.env` blob and the `customers.json` entry
2. Manually create a draft crawl-rules YAML at `src/etl_crawler/customer_configs/<customer_id>.yml` (refined in step 4)
3. Upload this draft to the registry container as `crawl_config.yml`:
   ```bash
   make upload-customer-etl-config customer_id=<customer_id>
   ```
4. **Test crawl rules locally first**, without touching the registry's `crawl_config.yml`:
   ```bash
   make scrape customer_name=<customer_id> ENV=dev local_crawl_rules=1
   ```
   Once satisfied, upload that same YAML to the registry container as `crawl_config.yml`:
   ```bash
   make upload-customer-etl-config customer_id=<customer_id>
   ```
5. For a fast first deployment (rather than waiting for the next scheduled all-customers run):
   ```bash
   make onboard-customer customer_id=<customer_id> ENV=dev
   ```
6. From then on, the regular scheduled job (`make pipeline-all-customers`) picks the customer up automatically — no code change or redeploy needed.

### Offboarding a customer

Set `ETL_ENABLED=False` in the customer's registry `config.env` (owned by the backend repo). The scheduled job then skips the customer quietly — no code change or redeploy needed.

This only stops future ETL runs. Existing data is **not** cleaned up automatically; for full removal, manually delete the Azure AI Search index (`SEARCH_INDEX_NAME`), the customer's run artifacts in the ETL files container, and — via the backend repo — the registry entry itself.

### Access to the registry

The ETL currently reads the registry using the same connection-string-based `BlobServiceClient` as `scripts/copy_secrets_from_container.py` (via `AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING`). If/when the registry is read via a managed identity instead, that identity needs **Storage Blob Data Reader** on the manifest container and every `customer-registry-*` container.

</details>

## Running the Pipeline Locally

<details>
<summary>Full pipeline (all 4 steps)</summary>

```bash
make pipeline customer_name={CUSTOMER_NAME} ENV=dev
```

This runs: crawl -> extract -> local_docs -> post_process -> index for a given customer. Crawl rules are fetched from the customer's registry `crawl_config.yml` blob by default -- add `local_crawl_rules=1` to use `src/etl_crawler/customer_configs/{CUSTOMER_NAME}.yml` instead (dev/test only, see [Customer Registry](#customer-registry)):

```bash
make pipeline customer_name={CUSTOMER_NAME} ENV=dev local_crawl_rules=1
```

To run the full pipeline for all customers, use

```bash
make pipeline-all-customers ENV=dev
```

### Individual step groups

Each command below is a **separate process invocation**. Without `data_dir`, it creates a new `data/{CUSTOMER_NAME}/{timestamp}/` directory, so it will not see files written by a previous step run in a different invocation (e.g. `post-process` right after `scrape` will fail with `Content JSONL not found`). To chain steps across separate commands, pass the same `data_dir` used by the prior step:

```bash
make scrape customer_name={CUSTOMER_NAME} ENV=dev
# note the printed data dir, e.g. data/{CUSTOMER_NAME}/{TIMESTAMP}
make post-process customer_name={CUSTOMER_NAME} ENV=dev data_dir=data/{CUSTOMER_NAME}/{TIMESTAMP}
```

**Scrape** (crawl + extract):

```bash
make scrape customer_name={CUSTOMER_NAME} ENV=dev local_crawl_rules=1
```

1. The Scrapy spider follows the rules defined in the registry's `crawl_config.yml` blob by default, or `src/etl_crawler/customer_configs/{CUSTOMER}.yml` when `local_crawl_rules=1` is passed, collecting URLs and PDF links into `url_list.jsonl`
2. Each URL is visited with Playwright (expanding accordions/tabs), and PDFs are downloaded and parsed. All content is written to `{CUSTOMER}_content.jsonl`

**Local docs** (optional — ingest local PDFs/text files):

```bash
make local-docs customer_name={CUSTOMER_NAME} ENV=dev data_dir=data/{CUSTOMER_NAME}/{timestamp}
```

Reads folders listed under `local_docs_dirs` in `src/etl_crawler/customer_configs/{CUSTOMER}.yml` (e.g. `data/bnf/extern_docs`, `data/bnf/internal_docs`), extracts text from `.pdf` and `.txt` files, and appends the results to `{CUSTOMER}_content.jsonl`. No-op if the customer config doesn't define `local_docs_dirs`.

**Post-process only:**

```bash
make post-process customer_name=CUSTOMER_NAME ENV=dev data_dir=data/{CUSTOMER_NAME}/{timestamp}
```

Reads `{CUSTOMER_NAME}_content.jsonl`, filters short/empty content, generates keywords and example questions via Azure OpenAI, and writes `processed_data.xlsx`.

**Index only:**

```bash
make index customer_name={CUSTOMER_NAME} ENV=dev data_dir=data/{CUSTOMER_NAME}/{timestamp}
```

Reads `processed_data.xlsx`, chunks documents with `SemanticChunker`, generates embeddings and titles, creates the Azure AI Search index `index_{CUSTOMER_NAME}`, and uploads all chunks.

**Post-process + index together:**

```bash
make etl customer_name={CUSTOMER_NAME} ENV=dev data_dir=data/{CUSTOMER_NAME}/{timestamp}
```

</details>



<details>
<summary>Using the Python CLI directly</summary>

```bash
PYTHONPATH=. python -m src.etl_crawler run --customer {CUSTOMER_NAME}
PYTHONPATH=. python -m src.etl_crawler run --customer {CUSTOMER_NAME} --steps crawl,extract
PYTHONPATH=. python -m src.etl_crawler run --customer {CUSTOMER_NAME} --steps post_process,index
PYTHONPATH=. python -m src.etl_crawler run --customer {CUSTOMER_NAME} --data-dir data/{CUSTOMER_NAME}/1234567890
```

### Notes

- The crawler config per customer is in `src/etl_crawler/customer_configs/{customer_name}.yml` for local dev/test use (`--local-crawl-rules`). Production runs read `crawl_config.yml` from the customer's registry blob container instead — see [Customer Registry](#customer-registry).
- Data artifacts are written to `data/{customer_name}/{timestamp}/` (gitignored)
- Index naming: the Azure AI Search index name is whatever `SEARCH_INDEX_NAME` is set to in the customer's registry `config.env` — used literally, not derived from the customer name.
- The pipeline does not handle scanned PDFs without a text layer

</details>

## Running Tests

<details>
<summary>Click to expand </summary>

### All tests:

```bash
make test
```

Skip benchmark tests (faster, no Azure required):

```bash
make test-quick
```

### Azure AI Search index checks (manual)

These use `curl` against the search REST API. They read `AZURE_SEARCH_ENDPOINT` and `AZURE_SEARCH_SERVICE_PRIMARY_ADMIN_KEY` from `.env.<ENV>.app` (e.g. `.env.dev.app`) and take the exact index name (`SEARCH_INDEX_NAME` from the customer's registry `config.env`) as a parameter — it's no longer derived from a customer name. Use a POSIX shell (e.g. Git Bash on Windows) so `grep`, `curl`, and `make` recipes behave as written.

**Sample documents (readable JSON)** — omits `text_vector` by default so output is not dominated by embeddings:

```bash
make search-probe ENV=dev index_name=index_{CUSTOMER_ID}
```

Optional: change API version (`SEARCH_API_VERSION`) or which fields are returned (`SEARCH_PROBE_SELECT`, comma-separated). Examples:

```bash
make search-probe ENV=dev index_name=index_{CUSTOMER_ID} SEARCH_PROBE_SELECT='chunk_id,Link,Title,chunk'
make search-probe ENV=dev index_name=index_{CUSTOMER_ID} SEARCH_PROBE_SELECT='*'
```

**Document count** — index statistics from the service:

```bash
make search-count ENV=dev index_name=index_index_{CUSTOMER_ID}
```

Prints `documentCount` and `storageSize`.

</details>

## Linting

<details>
<summary>Click to expand </summary>

```bash
make lint
```

</details>

## Provisioning and Deployment

The pipeline is deployed to Azure as two **Container Apps Jobs**:

- **dev job**: scheduled daily via cron
- **prod job**: manual trigger after dev validation


### Configuration

All Azure references are read from `.env.etl` in `Makefile` using:

```make
$(shell grep '^VAR=' .env.etl | cut -d '=' -f2-)
```

Required `.env.etl` keys:

- `AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING`
- `AZURE_CONTAINER_STORAGE_NAME`
- `AZURE_CONTAINER_STORAGE_SECRETS_NAME`
- `AZURE_CONTAINER_STORAGE_ETL_FILES_NAME`
- `AZURE_CUSTOMER_REGISTRY_ACCOUNT_URL`
- `AZURE_CUSTOMER_REGISTRY_MANIFEST_CONTAINER`
- `AZURE_CUSTOMER_REGISTRY_CONTAINER_PREFIX`
- `AZURE_ETL_RESOURCE_GROUP_NAME`
- `AZURE_CONTAINER_REGISTRY_NAME`
- `AZURE_CONTAINER_REGISTRY_LOGIN_SERVER`
- `AZURE_RESOURCE_GROUP_LOCATION`
- `AZURE_CONTAINER_APP_ENV_NAME`
- `WEBHOOK_URL` (optional)

The ETL artifact container configured by `AZURE_CONTAINER_STORAGE_ETL_FILES_NAME` is created automatically by the pipeline if it does not already exist.

Image and job naming are derived from `pyproject.toml`:

- `PROJECT_NAME` = `name` (e.g. `dsl-bot-etl`)
- `VERSION` = `version` (e.g. `0.1.0`)
- Job names = sanitized and truncated `{PROJECT_NAME}-{VERSION}-dev|prod` (e.g. `dsl-bot-etl-0-1-0-dev`)
- Image tag = `{ACR_LOGIN_SERVER}/{PROJECT_NAME}:{VERSION}` (e.g. `crdbglobal001.azurecr.io/dsl-bot-etl:0.1.0`)

### Deploy Container
The container image needs to be present beforehand as this is needed during the provisioning of the job (not infra)

1. Build/push image first:

```bash
make docker-build-image
```
2. Push Image

```bash
make docker-build-image
make docker-push-image ACR_USERNAME="<acr-user>" ACR_PASSWORD="<acr-password>"
```

### Provisioning Steps

1. Azure CLI installed and logged in (`az login`)
2. Configure the Environment Variables as described in [Configure the Environment Variables](#configure-the-environment-variables) section.
3. Provision the resource group and the container group (once only):

  ```bash
  make az-register-providers
  make provision-rg
  make provision-infra
  ```

### Testing Steps

To be implemented


### Create/ Update Crawl Jobs

1. Before updating any job, first build and push the latest image from the [Deploy Container](#deploy-container) section.

2. Update **dev** job (scheduled):
  ```bash
  make provision-dev ACR_USERNAME="<acr-user>" ACR_PASSWORD="<acr-password>"
  ```
   This command automatically stops and deletes older `*-dev` jobs from previous versions before creating the new one. This command also authenticates to the ACR to pull the image.
3. Verify dev job configuration:
  ```bash
  make job-name ENV=dev
  make job-trigger ENV=dev
  make job-cron ENV=dev
  ```
4. Update **prod** job (scheduled: every Sunday at 01:00 UTC):
  ```bash
  make provision-prod ACR_USERNAME="<acr-user>" ACR_PASSWORD="<acr-password>"
  ```
   This command automatically stops and deletes older `*-prod` jobs from previous versions before creating the new one. This command also authenticates to the ACR to pull the image.
5. Verify prod job configuration:
  ```bash
  make job-name ENV=prod
  make job-trigger ENV=prod
  make job-cron ENV=prod
  ```
  `job-cron` should return `0 1 * * 0` (every Sunday at 01:00 UTC).
6. Trigger `dev` and observe:
  ```bash
  make trigger ENV=dev
  make logs ENV=dev
7. Review the smoke test results. If approved, go to step 8. Otherwise, fix bug and repeat steps from 1-6.
8. Trigger `prod`
  make trigger ENV=prod PROD_APPROVED=YES
  make logs ENV=prod
  ```
9. To view logs after the end of the job, KQL queries can be run on `Azure portal/<YOUR_CONTAINER_APP_JOB>/Logs` [Optional]
  1. Example query to get container level logs
    ```bash
    ContainerAppSystemLogs_CL
  | where JobName_s == 'dsl-bot-etl-0-1-1-dev'
    ```
  2. Example query to get app level ephemeral logs
    ```bash
    ContainerAppConsoleLogs_CL
  | where TimeGenerated between (datetime(2026-03-04T02:00:00Z) .. datetime(2026-03-04T06:50:00Z))
  | where ContainerGroupName_s has "dsl-bot-etl-0-1-1-dev"
  | project TimeGenerated, Log_s
  | order by TimeGenerated desc
    ```


**Note:** Both `provision-dev` and `provision-prod` validate that the image tag exists in ACR before creating jobs.

### Scheduled flow

1. **01:00 UTC every Sunday** — both dev and prod jobs start automatically (`Schedule`)
2. Container runs `make run-scheduled`, chaining:
   - `copy-secrets-from-container`
   - `pipeline-all-customers`
   - `smoke-test`
   - `notify`
3. Smoke tests validate indexes by their registry `SEARCH_INDEX_NAME`
4. Webhook sends a status message to Teams/Slack

To trigger manually at any time:

```bash
make trigger ENV=dev
make trigger ENV=prod PROD_APPROVED=YES
```

### Key settings

- Dev job trigger: `--trigger-type Schedule --cron-expression "0 1 * * 0"` (every Sunday at 01:00 UTC)
- Prod job trigger: `--trigger-type Schedule --cron-expression "0 1 * * 0"` (every Sunday at 01:00 UTC)
- Job naming rule: lowercase alphanumeric + `-`, with version dots converted to dashes and base name trimmed to fit Azure's `<32` character limit after `-dev`/`-prod`
- Parallelism: `--parallelism 1`
- Replica completion count: `--replica-completion-count 1`
- Timeout: `--replica-timeout 28800` (8 hours)
- Retry: `--replica-retry-limit 1` (required by current Azure CLI for job creation)
- Resources: `--cpu 2 --memory 4Gi` (valid Consumption pairing)
- ACR: existing registry (`crdbglobal001`), no ACR provisioning target
- Secrets strategy: Storage connection string is read from `.env.etl`; ACR credentials are passed at runtime as `ACR_USERNAME` and `ACR_PASSWORD` when creating jobs
- Logging: `provision-infra` uses `--logs-destination none`, so it does not create or incur charges for a Log Analytics workspace. Persistent Container Apps logs and KQL queries are therefore unavailable unless a logging destination is configured later.


### Useful commands

| Command | Description |
|---|---|
| `make docker-build-image` | Build local Docker image (`bot-etl:{VERSION}`) |
| `make docker-push-image ACR_USERNAME="..." ACR_PASSWORD="..."` | Tag and push image to ACR |
| `make az-register-providers` | Register the providers when provisioning for the first time
| `make provision-rg` | Create ETL resource group (idempotent) |
| `make provision-infra` | Create Container Apps environment |
| `make provision-dev ACR_USERNAME="..." ACR_PASSWORD="..."` | Create/update dev job (requires ACR credentials) |
| `make provision-prod ACR_USERNAME="..." ACR_PASSWORD="..."` | Create/update prod job (requires ACR credentials) |
| `make jobs-list` | List all Container Apps jobs in the ETL resource group |
| `make job-name ENV=dev` | Print resolved job name for `ENV` |
| `make job-show ENV=dev` | Show full job configuration for `ENV` |
| `make job-trigger ENV=dev` | Show trigger type (`Schedule` or `Manual`) |
| `make job-cron ENV=dev` | Show cron expression (empty for manual jobs) |
| `make trigger ENV=dev` | Manually start the dev job |
| `make trigger ENV=prod PROD_APPROVED=YES` | Manually start the prod job (guarded) |
| `make kill ENV=dev` | Stop all currently running dev executions |
| `make kill ENV=prod` | Stop all currently running prod executions |
| `make logs ENV=dev` | Tail dev job logs (requires `ENV=dev|prod`) |
| `make logs ENV=prod` | Tail prod job logs (requires `ENV=dev|prod`) |
| `make smoke-test ENV=dev` | Run smoke tests locally against dev indexes |
| `make destroy-job ENV=dev DESTROY_CONFIRM=YES` | Delete only dev Container Apps job |
| `make destroy-job ENV=prod DESTROY_CONFIRM=YES` | Delete only prod Container Apps job |
| `make destroy-infra DESTROY_CONFIRM=YES` | Delete Container Apps environment |
