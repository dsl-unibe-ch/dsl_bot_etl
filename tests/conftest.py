"""Shared test fixtures."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.etl_crawler.config import AppSettings, ETLSettings
from src.etl_crawler.pipeline import RunContext


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    """Return a temporary data directory for a test run."""
    d = tmp_path / "test_customer" / "1234567890"
    d.mkdir(parents=True)
    return d


@pytest.fixture()
def mock_app_settings() -> AppSettings:
    """Return a mock AppSettings with dummy values."""
    return MagicMock(spec=AppSettings, **{
        "ENV": "test",
        "AZURE_SEARCH_SERVICE_PRIMARY_ADMIN_KEY": "fake-key",
        "AZURE_OPENAI_PRIMARY_KEY": "fake-key",
        "AZURE_SEARCH_ENDPOINT": "https://fake.search.windows.net",
        "AZURE_OPENAI_ENDPOINT": "https://fake.openai.azure.com",
        "AZURE_OPENAI_SEARCH_EMBEDDING_DEPLOYMENT": "text-embedding-3-large",
        "AZURE_OPENAI_SEARCH_EMBEDDING_API_VERSION": "2024-02-01",
        "AZURE_OPENAI_CHAT_DEPLOYMENT": "gpt-4.1",
        "AZURE_OPENAI_CHAT_API_VERSION": "2024-12-01-preview",
        "AZURE_OPENAI_VECTORIZER_ENDPOINT": "https://fake.openai.azure.com",
    })


@pytest.fixture()
def mock_etl_settings() -> ETLSettings:
    """Return a mock ETLSettings with dummy registry values."""
    return MagicMock(spec=ETLSettings, **{
        "AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING": "UseDevelopmentStorage=true",
        "AZURE_CONTAINER_STORAGE_NAME": "dsl-bot-logs",
        "AZURE_CONTAINER_STORAGE_SECRETS_NAME": "dsl-bot-secrets",
        "AZURE_CONTAINER_STORAGE_ETL_FILES_NAME": "dsl-bot-etl-files",
        "AZURE_CUSTOMER_REGISTRY_ACCOUNT_URL": "https://fake.blob.core.windows.net",
        "AZURE_CUSTOMER_REGISTRY_MANIFEST_CONTAINER": "customer-registry",
        "AZURE_CUSTOMER_REGISTRY_CONTAINER_PREFIX": "customer-registry-",
    })


@pytest.fixture()
def sample_customer_config() -> dict:
    """Return a minimal customer config for testing."""
    return {
        "seed_urls": ["https://example.com"],
        "allowed_domains": ["example.com"],
        "allow": ["/test/"],
        "deny_domains": [],
    }


@pytest.fixture()
def run_context(tmp_data_dir: Path, mock_app_settings: AppSettings, sample_customer_config: dict) -> RunContext:
    """Return a RunContext wired up for testing."""
    return RunContext(
        customer_name="test_customer",
        data_dir=tmp_data_dir,
        customer_config=sample_customer_config,
        app_settings=mock_app_settings,
        search_index_name="index_test_customer",
        root_urls=["https://example.com"],
    )
