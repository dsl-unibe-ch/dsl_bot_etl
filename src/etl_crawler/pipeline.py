"""Pipeline runner that orchestrates ETL steps."""

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.etl_crawler.blob_artifacts import ETLArtifactUploader
from src.etl_crawler.config import AppSettings, ETLSettings
from src.etl_crawler.registry import (
    load_crawl_rules,
    load_enabled_customers,
    load_registry_entry,
)
from src.etl_crawler.steps import crawl, extract, index, local_docs, post_process

logger = logging.getLogger(__name__)

CUSTOMER_CONFIGS_DIR = Path(__file__).parent / "customer_configs"

STEP_REGISTRY: dict[str, Any] = {
    "crawl": crawl.run,
    "extract": extract.run,
    "local_docs": local_docs.run,
    "post_process": post_process.run,
    "index": index.run,
}


@dataclass
class RunContext:
    """Shared context passed to every pipeline step."""

    customer_name: str
    data_dir: Path
    customer_config: dict
    app_settings: AppSettings
    search_index_name: str
    root_urls: list[str]


def load_customer_config(customer_name: str) -> dict:
    """Load a customer's crawl-rules YAML from the local repo (dev/test use only)."""
    config_path = CUSTOMER_CONFIGS_DIR / f"{customer_name}.yml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"No customer config found at {config_path}. "
            f"Available configs: {[p.stem for p in CUSTOMER_CONFIGS_DIR.glob('*.yml')]}"
        )
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_crawl_config(
    customer_name: str, etl_settings: ETLSettings, use_local_crawl_rules: bool
) -> dict:
    """Resolve crawl rules: local repo YAML (opt-in, dev/test) or registry blob (default).

    The scheduled/production job never passes ``use_local_crawl_rules=True``, so a
    customer's committed local YAML (if any) can never silently shadow their registry
    blob rules when actually deployed.
    """
    if use_local_crawl_rules:
        return load_customer_config(customer_name)
    return load_crawl_rules(etl_settings, customer_name)


def merge_seed_urls(root_urls: list[str], crawl_config: dict) -> list[str]:
    """Combine the registry's root URLs with any supplementary seed URLs.

    ``root_urls`` (from the customer registry's ``CUSTOMER_ROOT_URLS``) are the
    authoritative crawl entry points. ``crawl_config["additional_seed_urls"]`` is an
    optional extension point for seed URLs that aren't part of the registered roots.
    """
    merged = list(root_urls)
    for url in crawl_config.get("additional_seed_urls") or []:
        if url not in merged:
            merged.append(url)
    return merged


def resolve_seed_urls(
    customer_config: dict, root_urls: list[str], use_local_crawl_rules: bool
) -> list[str]:
    """Resolve the seed URLs to crawl with, depending on the crawl rules source.

    Local dev YAML is self-contained -- its own ``seed_urls`` are honored as-is.
    Otherwise (the registry/production path), ``root_urls`` (``CUSTOMER_ROOT_URLS``)
    are authoritative and merged with the crawl config's ``additional_seed_urls``.
    """
    if use_local_crawl_rules:
        return list(customer_config.get("seed_urls") or [])
    return merge_seed_urls(root_urls, customer_config)


def resolve_data_dir(customer_name: str, data_dir: Path | None = None) -> Path:
    """Resolve or create a timestamped data directory for the run.

    If *data_dir* is given and already exists (e.g. resuming a previous run),
    it is returned as-is.  Otherwise a new timestamped directory is created.
    """
    if data_dir and data_dir.exists():
        return data_dir

    base = Path("data") / customer_name
    if data_dir is None:
        data_dir = base / str(int(time.time()))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def run_pipeline(
    customer_name: str,
    steps: list[str] | None = None,
    data_dir: Path | None = None,
    use_local_crawl_rules: bool = False,
) -> None:
    """Run the ETL pipeline for a customer.

    Args:
        customer_name: Customer id, matching a registry container
            (``customer-registry-<customer_name>``).
        steps: Optional subset of steps to run (default: all steps in order).
        data_dir: Optional explicit data directory (default: new timestamped dir).
        use_local_crawl_rules: If True, load crawl rules from the local
            ``customer_configs/<customer_name>.yml`` instead of the registry blob.
            Dev/test only -- the scheduled/production job never sets this.
    """
    data_dir = resolve_data_dir(customer_name, data_dir)
    etl_settings = ETLSettings()
    app_settings = AppSettings()
    env_label = app_settings.ENV or "dev"
    if not etl_settings.AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING:
        raise ValueError("AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING is required")
    if not etl_settings.AZURE_CONTAINER_STORAGE_ETL_FILES_NAME:
        raise ValueError("AZURE_CONTAINER_STORAGE_ETL_FILES_NAME is required")

    registry_entry = load_registry_entry(etl_settings, customer_name)
    customer_config = resolve_crawl_config(
        customer_name, etl_settings, use_local_crawl_rules
    )
    customer_config["seed_urls"] = resolve_seed_urls(
        customer_config, registry_entry.root_urls, use_local_crawl_rules
    )

    run_prefix = f"{env_label}/{customer_name}/{data_dir.name}"
    artifact_uploader = ETLArtifactUploader(
        connection_string=etl_settings.AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING,
        container_name=etl_settings.AZURE_CONTAINER_STORAGE_ETL_FILES_NAME,
        run_prefix=run_prefix,
    )
    logger.info(
        "Artifact uploads enabled: container=%s run_prefix=%s",
        etl_settings.AZURE_CONTAINER_STORAGE_ETL_FILES_NAME,
        run_prefix,
    )

    run_context = RunContext(
        customer_name=customer_name,
        data_dir=data_dir,
        customer_config=customer_config,
        app_settings=app_settings,
        search_index_name=registry_entry.search_index_name,
        root_urls=registry_entry.root_urls,
    )

    requested_steps = steps or list(STEP_REGISTRY)

    for step_name in requested_steps:
        if step_name not in STEP_REGISTRY:
            raise ValueError(
                f"Unknown step '{step_name}'. Available: {list(STEP_REGISTRY)}"
            )

    logger.info(
        "Pipeline starting for customer=%s data_dir=%s steps=%s",
        customer_name,
        data_dir,
        requested_steps,
    )

    for step_name in requested_steps:
        logger.info("Running step: %s", step_name)
        STEP_REGISTRY[step_name](run_context)
        artifact_uploader.sync_run_outputs(run_context.data_dir)
        logger.info("Completed step: %s", step_name)

    logger.info("Pipeline finished.")


def run_pipeline_for_enabled_customers(steps: list[str] | None = None) -> None:
    """Run the pipeline for every customer currently marked ETL_ENABLED=True in the registry."""
    etl_settings = ETLSettings()
    entries = load_enabled_customers(etl_settings)
    if not entries:
        logger.warning("No ETL-enabled customers found in registry -- nothing to run.")
        return
    logger.info(
        "Registry returned %d ETL-enabled customer(s): %s",
        len(entries),
        [entry.customer_id for entry in entries],
    )
    for entry in entries:
        logger.info("Running pipeline for registry customer: %s", entry.customer_id)
        run_pipeline(entry.customer_id, steps=steps)
