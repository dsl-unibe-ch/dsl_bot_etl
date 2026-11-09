"""Tests for HTTP Basic Auth credential resolution."""

from unittest.mock import patch

import pytest

from src.etl_crawler.auth import resolve_basic_auth


class TestResolveBasicAuth:
    def test_not_configured_returns_none(self):
        assert resolve_basic_auth({}) is None

    def test_resolves_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("TEST_AUTH_USER", "alice")
        monkeypatch.setenv("TEST_AUTH_PASS", "s3cret")
        config = {
            "basic_auth": {
                "domain": "example.com",
                "username_env": "TEST_AUTH_USER",
                "password_env": "TEST_AUTH_PASS",
            }
        }
        assert resolve_basic_auth(config) == ("example.com", "alice", "s3cret")

    def test_falls_back_to_env_etl_file(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("TEST_AUTH_USER", raising=False)
        monkeypatch.delenv("TEST_AUTH_PASS", raising=False)
        config = {
            "basic_auth": {
                "domain": "example.com",
                "username_env": "TEST_AUTH_USER",
                "password_env": "TEST_AUTH_PASS",
            }
        }
        with patch(
            "src.etl_crawler.auth.dotenv_values",
            return_value={"TEST_AUTH_USER": "bob", "TEST_AUTH_PASS": "hunter2"},
        ):
            assert resolve_basic_auth(config) == ("example.com", "bob", "hunter2")

    def test_missing_env_vars_raises(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("MISSING_AUTH_USER", raising=False)
        monkeypatch.delenv("MISSING_AUTH_PASS", raising=False)
        config = {
            "basic_auth": {
                "domain": "example.com",
                "username_env": "MISSING_AUTH_USER",
                "password_env": "MISSING_AUTH_PASS",
            }
        }
        with (
            patch("src.etl_crawler.auth.dotenv_values", return_value={}),
            pytest.raises(RuntimeError, match="env var"),
        ):
            resolve_basic_auth(config)

    def test_incomplete_config_raises(self):
        config = {"basic_auth": {"domain": "example.com"}}
        with pytest.raises(ValueError, match="basic_auth config"):
            resolve_basic_auth(config)
