"""Tests for the extract step."""

import json
from pathlib import Path

from bs4 import BeautifulSoup

from src.etl_crawler.steps.extract import ContentExtractor, PDFContentExtractor


class TestContentExtractor:
    def test_extract_text_basic_html(self, tmp_path: Path):
        extractor = ContentExtractor("test", tmp_path)
        html = "<html><body><main><h1>Title</h1><p>Hello world</p></main></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        text = extractor.extract_text_content(soup)
        assert "Title" in text
        assert "Hello world" in text

    def test_extract_text_strips_scripts(self, tmp_path: Path):
        extractor = ContentExtractor("test", tmp_path)
        html = "<html><body><p>Real content</p><script>alert('x')</script></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        text = extractor.extract_text_content(soup)
        assert "Real content" in text
        assert "alert" not in text

    def test_extract_text_hyperlinks(self, tmp_path: Path):
        extractor = ContentExtractor("test", tmp_path)
        extractor.current_base_url = "https://example.com"
        html = '<html><body><a href="/about">About Us</a></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        text = extractor.extract_text_content(soup)
        assert "About Us" in text
        assert "https://example.com/about" in text


class TestPDFContentExtractor:
    def test_is_url(self):
        assert PDFContentExtractor.is_url("https://example.com/file.pdf")
        assert PDFContentExtractor.is_url("http://example.com/file.pdf")
        assert not PDFContentExtractor.is_url("/local/file.pdf")

    def test_process_pdf_missing_file(self, tmp_path: Path):
        extractor = PDFContentExtractor("test", tmp_path)
        result = extractor.process_pdf(tmp_path / "nonexistent.pdf", 1)
        assert result["success"] is False


class TestExtractStep:
    def test_run_raises_if_no_url_list(self, run_context):
        from src.etl_crawler.steps.extract import run

        try:
            run(run_context)
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_run_with_empty_url_list(self, run_context):
        from src.etl_crawler.steps.extract import run

        url_list = run_context.data_dir / "url_list.jsonl"
        url_list.write_text("", encoding="utf-8")
        result = run(run_context)
        assert result.url_count == 0
        assert result.pdf_count == 0
