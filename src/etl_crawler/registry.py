"""Customer registry: discovers customers and loads their identity/crawl config from Azure Blob Storage."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from io import StringIO

import yaml
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient
from dotenv import dotenv_values

from src.etl_crawler.config import ETLSettings

logger = logging.getLogger(__name__)

MANIFEST_BLOB_NAME = "customers.json"
CONFIG_ENV_BLOB_NAME = "config.env"
CRAWL_CONFIG_BLOB_NAME = "crawl_config.yml"

_TRUE_FALSE = {"true": True, "false": False}


class RegistryError(RuntimeError):
    """Raised when the customer registry manifest or a customer's config is unavailable or invalid."""


@dataclass
class CustomerRegistryEntry:
    """A single customer's identity/index configuration, parsed from their registry config.env."""

    customer_id: str
    root_urls: list[str]
    search_index_name: str
    etl_enabled: bool


def _require_registry_settings(etl_settings: ETLSettings) -> None:
    missing = [
        name
        for name, value in (
            (
                "AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING",
                etl_settings.AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING,
            ),
            (
                "AZURE_CUSTOMER_REGISTRY_MANIFEST_CONTAINER",
                etl_settings.AZURE_CUSTOMER_REGISTRY_MANIFEST_CONTAINER,
            ),
            (
                "AZURE_CUSTOMER_REGISTRY_CONTAINER_PREFIX",
                etl_settings.AZURE_CUSTOMER_REGISTRY_CONTAINER_PREFIX,
            ),
        )
        if not value
    ]
    if missing:
        raise RegistryError(
            f"Missing required customer registry settings: {', '.join(missing)}"
        )


def _blob_service_client(etl_settings: ETLSettings) -> BlobServiceClient:
    connection_string = etl_settings.AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING
    assert connection_string is not None  # noqa: S101 - validated by _require_registry_settings
    return BlobServiceClient.from_connection_string(connection_string)


def _download_blob_bytes(
    etl_settings: ETLSettings, container_name: str, blob_name: str
) -> bytes:
    client = _blob_service_client(etl_settings)
    container = client.get_container_client(container_name)
    try:
        return container.get_blob_client(blob_name).download_blob().readall()
    except ResourceNotFoundError as e:
        raise RegistryError(
            f"'{blob_name}' not found in container '{container_name}'"
        ) from e


def load_customer_ids(etl_settings: ETLSettings) -> list[str]:
    """Fetch and validate the customer_ids manifest (customers.json)."""
    _require_registry_settings(etl_settings)
    manifest_container = etl_settings.AZURE_CUSTOMER_REGISTRY_MANIFEST_CONTAINER
    assert manifest_container is not None  # noqa: S101 - validated by _require_registry_settings
    data = _download_blob_bytes(etl_settings, manifest_container, MANIFEST_BLOB_NAME)

    try:
        manifest = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RegistryError(f"{MANIFEST_BLOB_NAME} is not valid JSON: {e}") from e

    customer_ids = manifest.get("customer_ids") if isinstance(manifest, dict) else None
    if not isinstance(customer_ids, list) or not all(
        isinstance(c, str) for c in customer_ids
    ):
        raise RegistryError(
            f"{MANIFEST_BLOB_NAME} must be a JSON object with a 'customer_ids' list "
            f"of strings, got: {manifest!r}"
        )
    return customer_ids


def _customer_container_name(etl_settings: ETLSettings, customer_id: str) -> str:
    return f"{etl_settings.AZURE_CUSTOMER_REGISTRY_CONTAINER_PREFIX}{customer_id}"


def _load_config_env(
    etl_settings: ETLSettings, customer_id: str
) -> dict[str, str | None]:
    _require_registry_settings(etl_settings)
    container_name = _customer_container_name(etl_settings, customer_id)
    data = _download_blob_bytes(etl_settings, container_name, CONFIG_ENV_BLOB_NAME)
    return dotenv_values(stream=StringIO(data.decode("utf-8")))


def _required(customer_id: str, env: dict[str, str | None], key: str) -> str:
    value = env.get(key)
    if value is None or value == "":
        raise RegistryError(
            f"Customer '{customer_id}': missing required field '{key}' in {CONFIG_ENV_BLOB_NAME}"
        )
    return value


def _parse_entry(customer_id: str, env: dict[str, str | None]) -> CustomerRegistryEntry:
    config_customer_id = _required(customer_id, env, "CUSTOMER_ID")
    if config_customer_id != customer_id:
        raise RegistryError(
            f"Customer '{customer_id}': CUSTOMER_ID in {CONFIG_ENV_BLOB_NAME} "
            f"('{config_customer_id}') does not match its registry container id ('{customer_id}')"
        )

    raw_root_urls = _required(customer_id, env, "CUSTOMER_ROOT_URLS")
    try:
        root_urls = json.loads(raw_root_urls)
    except json.JSONDecodeError as e:
        raise RegistryError(
            f"Customer '{customer_id}': CUSTOMER_ROOT_URLS is not valid JSON: {raw_root_urls!r}"
        ) from e
    if not isinstance(root_urls, list) or not all(
        isinstance(u, str) for u in root_urls
    ):
        raise RegistryError(
            f"Customer '{customer_id}': CUSTOMER_ROOT_URLS must be a JSON array of "
            f"strings, got: {raw_root_urls!r}"
        )

    search_index_name = _required(customer_id, env, "SEARCH_INDEX_NAME")

    raw_etl_enabled = _required(customer_id, env, "ETL_ENABLED")
    etl_enabled = _TRUE_FALSE.get(raw_etl_enabled.strip().lower())
    if etl_enabled is None:
        raise RegistryError(
            f"Customer '{customer_id}': ETL_ENABLED must be 'True' or 'False', "
            f"got: {raw_etl_enabled!r}"
        )

    return CustomerRegistryEntry(
        customer_id=customer_id,
        root_urls=root_urls,
        search_index_name=search_index_name,
        etl_enabled=etl_enabled,
    )


def load_registry_entry(
    etl_settings: ETLSettings, customer_id: str
) -> CustomerRegistryEntry:
    """Fetch and parse a single customer's registry entry, regardless of ETL_ENABLED."""
    env = _load_config_env(etl_settings, customer_id)
    return _parse_entry(customer_id, env)


def load_enabled_customers(etl_settings: ETLSettings) -> list[CustomerRegistryEntry]:
    """Load every customer in the manifest and return only the ones with ETL_ENABLED=True.

    Fails fast (raises ``RegistryError``) if the manifest or any customer's config.env is
    missing or malformed -- there is no local fallback. A customer with ``ETL_ENABLED=False``
    is skipped quietly; this is expected, not an error.
    """
    customer_ids = load_customer_ids(etl_settings)
    enabled: list[CustomerRegistryEntry] = []
    for customer_id in customer_ids:
        entry = load_registry_entry(etl_settings, customer_id)
        if entry.etl_enabled:
            enabled.append(entry)
        else:
            logger.info("Skipping customer '%s': ETL_ENABLED=False", customer_id)
    return enabled


def load_crawl_rules(etl_settings: ETLSettings, customer_id: str) -> dict:
    """Fetch a customer's production crawl rules (crawl_config.yml) from their registry container."""
    _require_registry_settings(etl_settings)
    container_name = _customer_container_name(etl_settings, customer_id)
    data = _download_blob_bytes(etl_settings, container_name, CRAWL_CONFIG_BLOB_NAME)
    return yaml.safe_load(data) or {}
