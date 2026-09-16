"""Step (optional) — Local docs: ingest PDFs and text files from local folders into content.jsonl."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.etl_crawler.steps.extract import PDFContentExtractor

if TYPE_CHECKING:
    from src.etl_crawler.pipeline import RunContext

logger = logging.getLogger(__name__)

PDF_EXTENSIONS = {".pdf"}
TEXT_EXTENSIONS = {".txt"}


def process_text_files(text_paths: list[Path], output_file: Path) -> int:
    """Read plain text files and append results to *output_file*. Returns count processed."""
    count = 0
    for txt_path in text_paths:
        try:
            content = txt_path.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.error("Error processing %s: %s", txt_path.name, e)
            continue
        result = {
            "url": str(txt_path),
            "filename": txt_path.name,
            "timestamp": datetime.now(UTC).isoformat(),
            "content": content,
            "success": True,
        }
        with output_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        count += 1
    return count


@dataclass
class LocalDocsResult:
    content_jsonl_path: Path
    pdf_count: int
    text_count: int
    skipped_count: int


def run(run_context: RunContext) -> LocalDocsResult | None:
    """Ingest PDFs/text files listed under the customer config's `local_docs_dirs`.

    No-op (returns None) if the customer config doesn't define any `local_docs_dirs`.
    """
    local_dirs = run_context.customer_config.get("local_docs_dirs", [])
    if not local_dirs:
        logger.info("No local_docs_dirs configured; skipping local_docs step.")
        return None

    pdf_paths: list[Path] = []
    text_paths: list[Path] = []
    skipped_count = 0
    for dir_str in local_dirs:
        folder = Path(dir_str)
        if not folder.is_dir():
            logger.warning("local_docs_dirs entry not found: %s", folder)
            continue
        for file_path in sorted(folder.iterdir()):
            if not file_path.is_file():
                continue
            suffix = file_path.suffix.lower()
            if suffix in PDF_EXTENSIONS:
                pdf_paths.append(file_path)
            elif suffix in TEXT_EXTENSIONS:
                text_paths.append(file_path)
            else:
                skipped_count += 1
                logger.debug("Skipping unsupported local doc: %s", file_path)

    output_file = run_context.data_dir / f"{run_context.customer_name}_content.jsonl"
    logger.info(
        "Ingesting %d local PDFs and %d local text files from %s",
        len(pdf_paths),
        len(text_paths),
        local_dirs,
    )

    if pdf_paths:
        pdf_extractor = PDFContentExtractor(
            run_context.customer_name,
            run_context.data_dir,
            download_dir=run_context.data_dir / "raw" / "pdf_files",
        )
        pdf_extractor.process_pdfs([str(p) for p in pdf_paths], output_file)

    text_count = process_text_files(text_paths, output_file) if text_paths else 0

    result = LocalDocsResult(
        content_jsonl_path=output_file,
        pdf_count=len(pdf_paths),
        text_count=text_count,
        skipped_count=skipped_count,
    )
    logger.info(
        "Local docs ingestion finished: %d PDFs, %d text files, %d skipped -> %s",
        result.pdf_count,
        result.text_count,
        result.skipped_count,
        output_file,
    )
    return result
