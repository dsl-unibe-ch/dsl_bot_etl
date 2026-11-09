"""Step 1 — Crawl: run the Scrapy spider and produce url_list.jsonl."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from src.etl_crawler.auth import resolve_basic_auth
from src.etl_crawler.spiders.link_spider import LinkSpider

if TYPE_CHECKING:
    from src.etl_crawler.pipeline import RunContext

logger = logging.getLogger(__name__)


@dataclass
class CrawlResult:
    url_list_path: Path
    url_count: int


def run(run_context: RunContext) -> CrawlResult:
    """Run the link spider for the customer, writing url_list.jsonl."""
    output_path = run_context.data_dir / "url_list.jsonl"
    # Resolved from the registry (or local YAML in dev/test) by pipeline.run_pipeline().
    config_path = run_context.data_dir / "_resolved_crawl_config.yml"
    config_path.write_text(
        yaml.safe_dump(run_context.customer_config), encoding="utf-8"
    )

    settings = get_project_settings()
    settings.update(
        {
            "FEEDS": {
                str(output_path): {
                    "format": "jsonlines",
                    "encoding": "utf-8",
                    "overwrite": True,
                }
            },
            "JOBDIR": str(run_context.data_dir / "scrapy_job"),
            "LOG_LEVEL": "INFO",
        }
    )

    basic_auth = resolve_basic_auth(run_context.customer_config)
    if basic_auth:
        domain, username, password = basic_auth
        # HTTPAUTH_DOMAIN scopes credentials to this exact host (+ subdomains),
        # not the whole crawl -- other domains/customers are unaffected.
        settings.set("HTTPAUTH_USER", username, priority="cmdline")
        settings.set("HTTPAUTH_PASS", password, priority="cmdline")
        settings.set("HTTPAUTH_DOMAIN", domain, priority="cmdline")

    process = CrawlerProcess(settings)
    process.crawl(LinkSpider, config=str(config_path))
    process.start()

    url_count = 0
    if output_path.exists():
        url_count = sum(1 for _ in output_path.open(encoding="utf-8"))

    result = CrawlResult(url_list_path=output_path, url_count=url_count)
    logger.info(
        "Crawl finished: %d items in %s", result.url_count, result.url_list_path
    )
    return result
