"""Tests for the pipeline runner."""

from pathlib import Path

import pytest

from src.etl_crawler.pipeline import (
    RunContext,
    load_customer_config,
    resolve_data_dir,
)


class TestLoadCustomerConfig:
    def test_loads_existing_config(self):
        config = load_customer_config("quality")
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
    def test_dataclass_fields(self, ctx: RunContext):
        assert ctx.customer_name == "test_customer"
        assert ctx.data_dir.exists()
        assert isinstance(ctx.customer_config, dict)
