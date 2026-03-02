"""Tests for the post_process step."""

from src.etl_crawler.steps.post_process import (
    KeywordQuestionResponse,
    extract_urls_from_text,
    find_page_type,
)


class TestFindPageType:
    def test_contact_page(self):
        result = find_page_type("Kontakt: someone@unibe.ch")
        assert "contact/service" in result

    def test_forms_page(self):
        result = find_page_type("Download the PDF formular here")
        assert "forms/resources" in result

    def test_deadlines_page(self):
        result = find_page_type("Wichtige Fristen und Termine")
        assert "deadlines" in result

    def test_other_page(self):
        result = find_page_type("General information about the university")
        assert result == ["other"]

    def test_mixed_page(self):
        result = find_page_type("Kontakt for PDF download, Fristen beachten")
        assert "contact/service" in result
        assert "forms/resources" in result
        assert "deadlines" in result


class TestExtractUrls:
    def test_extracts_urls(self):
        text = "Visit https://example.com and http://test.org/page for info."
        urls = extract_urls_from_text(text)
        assert "https://example.com" in urls
        assert "http://test.org/page" in urls

    def test_strips_trailing_punctuation(self):
        text = "See https://example.com."
        urls = extract_urls_from_text(text)
        assert "https://example.com" in urls

    def test_empty_text(self):
        assert extract_urls_from_text("no urls here") == set()


class TestKeywordQuestionResponse:
    def test_schema_validation(self):
        resp = KeywordQuestionResponse(
            keywords=["a", "b"],
            questions=["q1", "q2"],
        )
        assert len(resp.keywords) == 2
        assert len(resp.questions) == 2


class TestPostProcessStep:
    def test_run_raises_if_no_content_jsonl(self, run_context):
        from src.etl_crawler.steps.post_process import run

        try:
            run(run_context)
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            pass
