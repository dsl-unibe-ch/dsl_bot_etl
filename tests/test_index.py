"""Tests for the index step."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.etl_crawler.pipeline import RunContext
from src.etl_crawler.steps.index import (
    EMBEDDING_MAX_TOKENS,
    AzureEmbeddingWrapper,
    _find_previous_run_json,
    _generate_change_summary,
    run,
)


class TestAzureEmbeddingWrapper:
    def _make_wrapper(self) -> tuple[AzureEmbeddingWrapper, MagicMock]:
        client = MagicMock()
        client.embeddings.create.return_value.data = [MagicMock(embedding=[0.1, 0.2])]
        return AzureEmbeddingWrapper(client, "test-deployment"), client

    def test_short_text_sent_unchanged(self):
        wrapper, client = self._make_wrapper()
        wrapper.embed_query("hello world")
        client.embeddings.create.assert_called_once_with(
            input=["hello world"], model="test-deployment"
        )

    def test_long_text_truncated_to_token_limit(self):
        wrapper, client = self._make_wrapper()
        long_text = "word " * (EMBEDDING_MAX_TOKENS * 2)
        wrapper.embed_query(long_text)
        sent_text = client.embeddings.create.call_args.kwargs["input"][0]
        assert len(wrapper._encoding.encode(sent_text)) <= EMBEDDING_MAX_TOKENS
        assert len(sent_text) < len(long_text)


class TestGenerateChangeSummary:
    def test_first_run_no_previous(self):
        docs = [{"Link": "https://a.com"}, {"Link": "https://b.com"}]
        summary = _generate_change_summary(docs, None)
        assert summary["status"] == "first_run"
        assert summary["new_chunk_count"] == 2

    def test_first_run_missing_path(self, tmp_path: Path):
        docs = [{"Link": "https://a.com"}]
        summary = _generate_change_summary(docs, tmp_path / "nonexistent.json")
        assert summary["status"] == "first_run"

    def test_added_and_removed_sources(self, tmp_path: Path):
        old_docs = [
            {"Link": "https://a.com"},
            {"Link": "https://b.com"},
        ]
        prev_json = tmp_path / "prev.json"
        prev_json.write_text(json.dumps(old_docs), encoding="utf-8")

        new_docs = [
            {"Link": "https://b.com"},
            {"Link": "https://c.com"},
            {"Link": "https://c.com"},
        ]
        summary = _generate_change_summary(new_docs, prev_json)

        assert summary["status"] == "update"
        assert summary["old_chunk_count"] == 2
        assert summary["new_chunk_count"] == 3
        assert summary["added_sources"] == ["https://c.com"]
        assert summary["removed_sources"] == ["https://a.com"]
        assert summary["unchanged_source_count"] == 1

    def test_no_changes(self, tmp_path: Path):
        docs = [{"Link": "https://a.com"}, {"Link": "https://b.com"}]
        prev_json = tmp_path / "prev.json"
        prev_json.write_text(json.dumps(docs), encoding="utf-8")

        summary = _generate_change_summary(docs, prev_json)
        assert summary["added_sources"] == []
        assert summary["removed_sources"] == []
        assert summary["unchanged_source_count"] == 2


class TestFindPreviousRunJson:
    def test_no_customer_dir(self, tmp_path: Path):
        result = _find_previous_run_json(tmp_path / "nonexistent" / "12345", "dev")
        assert result is None

    def test_no_previous_runs(self, tmp_path: Path):
        current = tmp_path / "customer" / "12345"
        current.mkdir(parents=True)
        result = _find_previous_run_json(current, "dev")
        assert result is None

    def test_finds_latest_previous(self, tmp_path: Path):
        customer = tmp_path / "customer"

        old_run = customer / "1000"
        old_run.mkdir(parents=True)
        old_json = old_run / "processed_data_azure_semantic_search_dev.json"
        old_json.write_text("[]", encoding="utf-8")

        newer_run = customer / "2000"
        newer_run.mkdir(parents=True)
        newer_json = newer_run / "processed_data_azure_semantic_search_dev.json"
        newer_json.write_text("[]", encoding="utf-8")

        current = customer / "3000"
        current.mkdir(parents=True)

        result = _find_previous_run_json(current, "dev")
        assert result == newer_json

    def test_ignores_current_dir(self, tmp_path: Path):
        customer = tmp_path / "customer"

        current = customer / "1000"
        current.mkdir(parents=True)
        (current / "processed_data_azure_semantic_search_dev.json").write_text("[]", encoding="utf-8")

        result = _find_previous_run_json(current, "dev")
        assert result is None


class TestRunUsesExactIndexName:
    def test_passes_search_index_name_literally(self, run_context: RunContext):
        (run_context.data_dir / "processed_data.xlsx").write_bytes(b"fake-xlsx")
        run_context.search_index_name = "totally-custom-name"

        with patch("src.etl_crawler.steps.index.run_etl") as mock_run_etl:
            mock_run_etl.return_value = {
                "index_name": "totally-custom-name",
                "chunk_count": 0,
            }
            result = run(run_context)

        mock_run_etl.assert_called_once_with(
            run_context.data_dir / "processed_data.xlsx",
            "totally-custom-name",
            run_context.app_settings,
            run_context.data_dir,
        )
        assert result.index_name == "totally-custom-name"
        # Must never fall back to the old index_{customer_name} derivation.
        assert not mock_run_etl.call_args[0][1].startswith("index_test_customer")
