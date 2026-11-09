"""Tests for the customer registry module."""

from unittest.mock import patch

import pytest

from src.etl_crawler.registry import (
    CustomerRegistryEntry,
    RegistryError,
    load_customer_ids,
    load_enabled_customers,
    load_registry_entry,
)


class _FakeDownload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def readall(self) -> bytes:
        return self._data


class _FakeBlobClient:
    def __init__(self, data: bytes | None) -> None:
        self._data = data

    def download_blob(self) -> _FakeDownload:
        if self._data is None:
            from azure.core.exceptions import ResourceNotFoundError

            raise ResourceNotFoundError("The specified blob does not exist.")
        return _FakeDownload(self._data)


class _FakeContainerClient:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    def get_blob_client(self, blob_name: str) -> _FakeBlobClient:
        return _FakeBlobClient(self._blobs.get(blob_name))


class FakeBlobServiceClient:
    """Minimal stand-in for azure.storage.blob.BlobServiceClient."""

    def __init__(self, containers: dict[str, dict[str, bytes]]) -> None:
        self._containers = containers

    def get_container_client(self, container_name: str) -> _FakeContainerClient:
        return _FakeContainerClient(self._containers.get(container_name, {}))


def _config_env_bytes(
    customer_id: str,
    root_urls: str = '["https://example.com"]',
    search_index_name: str = "index_example",
    etl_enabled: str = "True",
    **extra: str,
) -> bytes:
    lines = [
        f"CUSTOMER_ID={customer_id}",
        f"CUSTOMER_ROOT_URLS={root_urls}",
        f"SEARCH_INDEX_NAME={search_index_name}",
        f"ETL_ENABLED={etl_enabled}",
        *[f"{key}={value}" for key, value in extra.items()],
    ]
    return "\n".join(lines).encode("utf-8")


def _manifest_bytes(customer_ids: list[str]) -> bytes:
    import json

    return json.dumps({"customer_ids": customer_ids}).encode("utf-8")


def _patched(containers: dict[str, dict[str, bytes]]):
    return patch(
        "src.etl_crawler.registry.BlobServiceClient.from_connection_string",
        return_value=FakeBlobServiceClient(containers),
    )


class TestLoadCustomerIds:
    def test_manifest_missing(self, mock_etl_settings):
        with _patched({}), pytest.raises(RegistryError, match="customers.json"):
            load_customer_ids(mock_etl_settings)

    def test_manifest_invalid_json(self, mock_etl_settings):
        containers = {"customer-registry": {"customers.json": b"not json"}}
        with _patched(containers), pytest.raises(RegistryError, match="not valid JSON"):
            load_customer_ids(mock_etl_settings)

    def test_manifest_wrong_shape(self, mock_etl_settings):
        containers = {"customer-registry": {"customers.json": b'{"foo": "bar"}'}}
        with _patched(containers), pytest.raises(RegistryError, match="customer_ids"):
            load_customer_ids(mock_etl_settings)

    def test_manifest_success(self, mock_etl_settings):
        containers = {
            "customer-registry": {"customers.json": _manifest_bytes(["bnf", "default"])}
        }
        with _patched(containers):
            assert load_customer_ids(mock_etl_settings) == ["bnf", "default"]


class TestLoadRegistryEntry:
    def test_config_env_missing(self, mock_etl_settings):
        with _patched({}), pytest.raises(RegistryError, match="config.env"):
            load_registry_entry(mock_etl_settings, "bnf")

    @pytest.mark.parametrize("missing_field", ["CUSTOMER_ID", "CUSTOMER_ROOT_URLS", "SEARCH_INDEX_NAME", "ETL_ENABLED"])
    def test_malformed_missing_required_field(self, mock_etl_settings, missing_field):
        fields = {
            "CUSTOMER_ID": "bnf",
            "CUSTOMER_ROOT_URLS": '["https://bnf.example.com"]',
            "SEARCH_INDEX_NAME": "index_bnf",
            "ETL_ENABLED": "True",
        }
        del fields[missing_field]
        content = "\n".join(f"{k}={v}" for k, v in fields.items()).encode("utf-8")
        containers = {"customer-registry-bnf": {"config.env": content}}
        with _patched(containers), pytest.raises(RegistryError, match=missing_field):
            load_registry_entry(mock_etl_settings, "bnf")

    def test_malformed_root_urls_not_json(self, mock_etl_settings):
        containers = {
            "customer-registry-bnf": {
                "config.env": _config_env_bytes("bnf", root_urls="not-json")
            }
        }
        with _patched(containers), pytest.raises(RegistryError, match="CUSTOMER_ROOT_URLS"):
            load_registry_entry(mock_etl_settings, "bnf")

    def test_malformed_root_urls_not_a_list(self, mock_etl_settings):
        containers = {
            "customer-registry-bnf": {
                "config.env": _config_env_bytes("bnf", root_urls='"https://bnf.example.com"')
            }
        }
        with _patched(containers), pytest.raises(RegistryError, match="CUSTOMER_ROOT_URLS"):
            load_registry_entry(mock_etl_settings, "bnf")

    def test_malformed_etl_enabled_value(self, mock_etl_settings):
        containers = {
            "customer-registry-bnf": {
                "config.env": _config_env_bytes("bnf", etl_enabled="Maybe")
            }
        }
        with _patched(containers), pytest.raises(RegistryError, match="ETL_ENABLED"):
            load_registry_entry(mock_etl_settings, "bnf")

    def test_customer_id_mismatch(self, mock_etl_settings):
        containers = {
            "customer-registry-bnf": {"config.env": _config_env_bytes("someone_else")}
        }
        with _patched(containers), pytest.raises(RegistryError, match="does not match"):
            load_registry_entry(mock_etl_settings, "bnf")

    def test_ignores_unrelated_backend_frontend_keys(self, mock_etl_settings):
        containers = {
            "customer-registry-bnf": {
                "config.env": _config_env_bytes(
                    "bnf",
                    BACKEND_PROMPT="some prompt text",
                    FRONTEND_ORIGIN="http://localhost:5173",
                    LIFECYCLE_STATUS="active",
                )
            }
        }
        with _patched(containers):
            entry = load_registry_entry(mock_etl_settings, "bnf")
        assert entry.customer_id == "bnf"

    def test_exact_index_name_used_literally(self, mock_etl_settings):
        containers = {
            "customer-registry-weird": {
                "config.env": _config_env_bytes(
                    "weird", search_index_name="totally-custom-name-not-prefixed"
                )
            }
        }
        with _patched(containers):
            entry = load_registry_entry(mock_etl_settings, "weird")
        assert entry.search_index_name == "totally-custom-name-not-prefixed"


class TestLoadEnabledCustomers:
    def test_disabled_customer_is_skipped_without_error(self, mock_etl_settings):
        containers = {
            "customer-registry": {"customers.json": _manifest_bytes(["bnf"])},
            "customer-registry-bnf": {
                "config.env": _config_env_bytes("bnf", etl_enabled="False")
            },
        }
        with _patched(containers):
            assert load_enabled_customers(mock_etl_settings) == []

    def test_multiple_customers_mixed_enabled_disabled(self, mock_etl_settings):
        containers = {
            "customer-registry": {"customers.json": _manifest_bytes(["a", "b", "c"])},
            "customer-registry-a": {
                "config.env": _config_env_bytes(
                    "a", search_index_name="index_a", etl_enabled="True"
                )
            },
            "customer-registry-b": {
                "config.env": _config_env_bytes("b", etl_enabled="False")
            },
            "customer-registry-c": {
                "config.env": _config_env_bytes(
                    "c", search_index_name="index_c", etl_enabled="True"
                )
            },
        }
        with _patched(containers):
            entries = load_enabled_customers(mock_etl_settings)
        assert [e.customer_id for e in entries] == ["a", "c"]
        assert all(isinstance(e, CustomerRegistryEntry) for e in entries)
        assert [e.search_index_name for e in entries] == ["index_a", "index_c"]

    def test_one_malformed_customer_fails_the_whole_load(self, mock_etl_settings):
        containers = {
            "customer-registry": {"customers.json": _manifest_bytes(["good", "bad"])},
            "customer-registry-good": {
                "config.env": _config_env_bytes("good", etl_enabled="True")
            },
            "customer-registry-bad": {
                "config.env": _config_env_bytes("bad", etl_enabled="not-a-bool")
            },
        }
        with _patched(containers), pytest.raises(RegistryError, match="ETL_ENABLED"):
            load_enabled_customers(mock_etl_settings)
