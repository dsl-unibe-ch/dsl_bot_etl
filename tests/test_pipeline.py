"""Tests for the pipeline runner."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.etl_crawler.pipeline import (
    RunContext,
    load_customer_config,
    merge_seed_urls,
    resolve_crawl_config,
    resolve_data_dir,
    resolve_seed_urls,
)


class TestLoadCustomerConfig:
    def test_loads_existing_config(self):
        config = load_customer_config("bnf")
        assert "seed_urls" in config
        assert isinstance(config["seed_urls"], list)

    def test_raises_for_missing_config(self):
        with pytest.raises(FileNotFoundError, match="No customer config found"):
            load_customer_config("nonexistent_customer")


class TestResolveDataDir:
    def test_creates_new_timestamped_dir(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data_dir = resolve_data_dir("test_customer")
        assert data_dir.exists()
        assert "test_customer" in str(data_dir)

    def test_uses_existing_dir(self, tmp_path: Path):
        existing = tmp_path / "my_dir"
        existing.mkdir()
        result = resolve_data_dir("test_customer", data_dir=existing)
        assert result == existing


class TestRunContext:
    def test_dataclass_fields(self, run_context: RunContext):
        assert run_context.customer_name == "test_customer"
        assert run_context.data_dir.exists()
        assert isinstance(run_context.customer_config, dict)
        assert run_context.search_index_name == "index_test_customer"
        assert run_context.root_urls == ["https://example.com"]


class TestMergeSeedUrls:
    def test_root_urls_only(self):
        assert merge_seed_urls(["https://a.com"], {}) == ["https://a.com"]

    def test_appends_additional_seed_urls(self):
        crawl_config = {"additional_seed_urls": ["https://b.com"]}
        assert merge_seed_urls(["https://a.com"], crawl_config) == [
            "https://a.com",
            "https://b.com",
        ]

    def test_deduplicates_preserving_order(self):
        crawl_config = {"additional_seed_urls": ["https://a.com", "https://b.com"]}
        assert merge_seed_urls(["https://a.com"], crawl_config) == [
            "https://a.com",
            "https://b.com",
        ]

    def test_no_additional_seed_urls_key(self):
        assert merge_seed_urls(["https://a.com"], {"allow": []}) == ["https://a.com"]


class TestResolveSeedUrls:
    def test_local_uses_customer_config_seed_urls_as_is(self):
        customer_config = {"seed_urls": ["https://local-a.com", "https://local-b.com"]}
        assert resolve_seed_urls(customer_config, ["https://root.com"], True) == [
            "https://local-a.com",
            "https://local-b.com",
        ]

    def test_local_with_no_seed_urls_key_returns_empty(self):
        assert resolve_seed_urls({}, ["https://root.com"], True) == []

    def test_registry_merges_root_urls_with_additional_seed_urls(self):
        customer_config = {
            "seed_urls": ["https://ignored.com"],
            "additional_seed_urls": ["https://extra.com"],
        }
        assert resolve_seed_urls(customer_config, ["https://root.com"], False) == [
            "https://root.com",
            "https://extra.com",
        ]


class TestResolveCrawlConfig:
    def test_local_opt_in_uses_local_yaml(self, mock_etl_settings):
        config = resolve_crawl_config("bnf", mock_etl_settings, use_local_crawl_rules=True)
        assert "seed_urls" in config

    def test_default_fetches_from_registry_blob(self, mock_etl_settings):
        with patch("src.etl_crawler.pipeline.load_crawl_rules") as mock_load:
            mock_load.return_value = {"seed_urls": [], "allowed_domains": []}
            config = resolve_crawl_config("bnf", mock_etl_settings, use_local_crawl_rules=False)
        mock_load.assert_called_once_with(mock_etl_settings, "bnf")
        assert config == {"seed_urls": [], "allowed_domains": []}
