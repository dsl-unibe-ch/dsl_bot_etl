"""Tests for the crawl step."""

from pathlib import Path

import pytest

from src.etl_crawler.spiders.link_spider import LinkSpider, _as_list


class TestAsListHelper:
    def test_none(self):
        assert _as_list(None) == []

    def test_empty_string(self):
        assert _as_list("") == []

    def test_csv_string(self):
        assert _as_list("a, b, c") == ["a", "b", "c"]

    def test_list(self):
        assert _as_list(["a", "b"]) == ["a", "b"]

    def test_list_with_empty_entries(self):
        assert _as_list(["a", "", "  ", "b"]) == ["a", "b"]


class TestLinkSpider:
    def test_spider_init_minimal(self, tmp_path: Path):
        config = tmp_path / "minimal.yml"
        config.write_text("seed_urls: []\n", encoding="utf-8")
        spider = LinkSpider(config=str(config))
        assert spider.name == "link_spider"
        assert spider.start_urls == []
        assert spider.static_pdfs == []

    def test_spider_init_with_yaml(self, tmp_path: Path):
        config = tmp_path / "test.yml"
        config.write_text(
            "seed_urls:\n"
            "  - https://example.com\n"
            "allowed_domains:\n"
            "  - example.com\n"
            "static_pdfs:\n"
            "  - https://example.com/doc.pdf\n",
            encoding="utf-8",
        )
        spider = LinkSpider(config=str(config))
        assert spider.start_urls == ["https://example.com"]
        assert spider.allowed_domains == ["example.com"]
        assert spider.static_pdfs == ["https://example.com/doc.pdf"]


class TestRunBasicAuthSettings:
    def test_sets_httpauth_settings_when_configured(
        self, run_context, monkeypatch: pytest.MonkeyPatch
    ):
        from unittest.mock import patch

        from src.etl_crawler.steps.crawl import run

        monkeypatch.setenv("TEST_AUTH_USER", "alice")
        monkeypatch.setenv("TEST_AUTH_PASS", "s3cret")
        run_context.customer_config["basic_auth"] = {
            "domain": "example.com",
            "username_env": "TEST_AUTH_USER",
            "password_env": "TEST_AUTH_PASS",
        }

        with patch("src.etl_crawler.steps.crawl.CrawlerProcess") as mock_process_cls:
            run(run_context)

        settings = mock_process_cls.call_args[0][0]
        assert settings["HTTPAUTH_USER"] == "alice"
        assert settings["HTTPAUTH_PASS"] == "s3cret"
        assert settings["HTTPAUTH_DOMAIN"] == "example.com"

    def test_no_httpauth_settings_when_not_configured(self, run_context):
        from unittest.mock import patch

        from src.etl_crawler.steps.crawl import run

        with patch("src.etl_crawler.steps.crawl.CrawlerProcess") as mock_process_cls:
            run(run_context)

        settings = mock_process_cls.call_args[0][0]
        assert not settings.get("HTTPAUTH_USER")
        assert not settings.get("HTTPAUTH_DOMAIN")
