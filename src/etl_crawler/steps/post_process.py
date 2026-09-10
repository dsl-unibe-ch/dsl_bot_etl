"""Step 3 — Post-process: enrich content.jsonl with keywords/questions via Azure OpenAI."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import requests
from openai import AzureOpenAI
from pydantic import BaseModel
from tqdm import tqdm

if TYPE_CHECKING:
    from src.etl_crawler.config import AppSettings
    from src.etl_crawler.pipeline import RunContext

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

KEYWORD_QUESTION_SYSTEM_PROMPT = """
You are generating metadata for a RAG knowledge base entry.

Goal:
1) Propose 3-5 KEYWORDS that help retrieval.
2) Propose 2-3 MATCHING QUESTIONS that real users might ask and that are answerable from the provided data.

Strict rules:
- Do NOT invent facts.
- Every question must be answerable from either (a) structured_facts or (b) cleaned_text.
- If the page is mostly a contact/ service list, prioritize "who/whom/contact/email/role/responsible" questions.
- If the page is mostly a form/ resource list, prioritize "form/ resource/ download/ pdf" questions.
- If the page is mostly a deadline list, prioritize "deadline/ frist/ due date" questions.
- Output JSON only, matching the schema.

Inputs:
URL: {url}
PAGE_TYPE: {page_type}
TEXT: {text}

Output schema:
{{
  "keywords": ["kw1", "kw2", "kw3"],
  "questions": [
    "q1",
    "q2",
    "q3"
  ]
}}
"""


class KeywordQuestionResponse(BaseModel):
    """Schema for keyword and question generation response."""

    keywords: list[str]
    questions: list[str]


def find_page_type(text: str) -> list[str]:
    """Find the page type of the text."""
    text_lower = text.lower()
    page_type: list[str] = []
    if any(
        text_lower.count(kw) > 0
        for kw in ("@unibe.ch", "kontakt", "zuständig", "ansprechpartner", "beratung")
    ):
        page_type.append("contact/service")
    if any(text_lower.count(kw) > 0 for kw in ("pdf", "download", "formular")):
        page_type.append("forms/resources")
    if text_lower.count("fristen") > 0:
        page_type.append("deadlines")
    return page_type or ["other"]


def post_process_data(
    jsonl_file: Path,
    customer_name: str,
    settings: AppSettings,
) -> list[dict]:
    """Read content JSONL, enrich each entry, return list of processed rows."""
    client = AzureOpenAI(
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=settings.AZURE_OPENAI_PRIMARY_KEY,
        api_version=settings.AZURE_OPENAI_CHAT_API_VERSION,
    )

    all_data: list[dict] = []
    with jsonl_file.open("r", encoding="utf-8") as f:
        for line in f:
            all_data.append(json.loads(line))

    valid_data = [r for r in all_data if r.get("content") and len(r["content"]) >= 10]
    filtered_count = len(all_data) - len(valid_data)
    if filtered_count:
        logger.warning(
            "Filtered out %d entries with empty/short content", filtered_count
        )
    logger.info(
        "Processing %d valid entries out of %d total", len(valid_data), len(all_data)
    )

    processed_data: list[dict] = []
    for idx, row in tqdm(
        enumerate(valid_data), total=len(valid_data), desc="Post-processing"
    ):
        url = row.get("url", "None")
        text = row["content"]

        if url.endswith(".pdf"):
            title = row.get("filename", "Untitled")
            category = "PDF"
        elif url == "None":
            title = "Untitled"
            category = "Other"
        else:
            title = text.split("\n\n")[0] if text else "Untitled"
            category = "Website"

        page_type = find_page_type(text)
        prompt = KEYWORD_QUESTION_SYSTEM_PROMPT.format(
            url=url, page_type=page_type, text=text
        )
        response = client.beta.chat.completions.parse(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[{"role": "system", "content": prompt}],
            response_format=KeywordQuestionResponse,
        )
        parsed = response.choices[0].message.parsed
        processed_data.append(
            {
                "DocumentID": f"{customer_name}_{idx}",
                "Link": url,
                "Title": title,
                "Category": category,
                "Local_Path": "Not Specified",
                "Local_Path_PDF": "Not Specified",
                "Date_Last_Modified": "Not Specified",
                "Data_Gathered_On": row.get("timestamp", "Not Specified"),
                "text": text,
                "Keyword": ", ".join(parsed.keywords),
                "Example_Questions": ", ".join(parsed.questions),
                "page_type": page_type,
            }
        )
    return processed_data


def extract_urls_from_text(text: str) -> set[str]:
    url_pattern = r"https?://[^\s\)\]<>]+"
    urls = re.findall(url_pattern, text)
    return {url.rstrip(".,;:") for url in urls}


def check_url_valid(url: str, timeout: int = 10) -> bool:
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        if response.status_code == 405:
            response = requests.get(
                url, timeout=timeout, allow_redirects=True, stream=True
            )
        return 200 <= response.status_code < 400
    except Exception:
        return False


def verify_urls_in_processed_data(processed_file: Path) -> list[str]:
    df = pd.read_excel(processed_file, engine="openpyxl")
    all_urls: set[str] = set()
    for text in df["text"]:
        if pd.notna(text):
            all_urls.update(extract_urls_from_text(str(text)))
    logger.info("Found %d unique URLs in processed data", len(all_urls))
    invalid: list[str] = []
    for url in tqdm(sorted(all_urls), desc="Checking URLs"):
        if not check_url_valid(url):
            invalid.append(url)
    return invalid


def find_empty_text_content(processed_file: Path) -> pd.DataFrame:
    df = pd.read_excel(processed_file, engine="openpyxl")
    return df[df["text"].isna()]


# ---------------------------------------------------------------------------
# Step entry-point
# ---------------------------------------------------------------------------


@dataclass
class PostProcessResult:
    output_xlsx: Path
    row_count: int
    invalid_urls: list[str]


def run(run_context: RunContext) -> PostProcessResult:
    """Post-process content.jsonl into processed_data.xlsx."""
    jsonl_file = run_context.data_dir / f"{run_context.customer_name}_content.jsonl"
    if not jsonl_file.exists():
        raise FileNotFoundError(f"Content JSONL not found: {jsonl_file}")

    all_data = post_process_data(
        jsonl_file, run_context.customer_name, run_context.app_settings
    )

    output_file = run_context.data_dir / "processed_data.xlsx"
    df = pd.DataFrame(all_data)
    df.to_excel(output_file, index=False, engine="openpyxl")
    logger.info("Saved %d entries to %s", len(all_data), output_file)

    invalid_urls = verify_urls_in_processed_data(output_file)
    if invalid_urls:
        logger.warning("Found %d potentially broken URLs:", len(invalid_urls))
        for i, url in enumerate(invalid_urls, start=1):
            logger.warning("  %d. %s", i, url)

    empty = find_empty_text_content(output_file)
    if not empty.empty:
        logger.warning("Found %d entries with empty text content", len(empty))

    result = PostProcessResult(
        output_xlsx=output_file,
        row_count=len(all_data),
        invalid_urls=invalid_urls,
    )
    logger.info("Post-processing finished: %d rows", result.row_count)
    return result
