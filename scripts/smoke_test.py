"""Post-pipeline smoke tests that validate AI Search indexes are healthy."""

import argparse
import json
import logging
import os
import sys

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient

from src.etl_crawler.config import AppSettings

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _get_customer_list() -> list[str]:
    raw = os.getenv("CUSTOMER_NAME_LIST", "")
    return raw.split() if raw else []


def _check_index(settings: AppSettings, index_name: str) -> dict:
    """Run health checks against a single AI Search index."""
    credential = AzureKeyCredential(settings.AZURE_SEARCH_SERVICE_PRIMARY_ADMIN_KEY)
    result: dict = {"index": index_name, "passed": True, "checks": {}}

    index_client = SearchIndexClient(settings.AZURE_SEARCH_ENDPOINT, credential)
    try:
        stats = index_client.get_index_statistics(index_name)
        doc_count = stats.get("document_count", stats.get("documentCount", 0))
        result["checks"]["exists"] = True
        result["checks"]["document_count"] = doc_count
        if doc_count == 0:
            result["passed"] = False
            result["checks"]["error"] = "Index is empty"
            return result
    except HttpResponseError as exc:
        result["passed"] = False
        result["checks"]["exists"] = False
        result["checks"]["error"] = str(exc)
        return result

    search_client = SearchClient(
        settings.AZURE_SEARCH_ENDPOINT, index_name, credential
    )
    try:
        results = search_client.search(search_text="*", top=1)
        first = next(results, None)
        result["checks"]["search_returns_results"] = first is not None
        if first is None:
            result["passed"] = False
            result["checks"]["error"] = "Search query returned no results"
    except HttpResponseError as exc:
        result["passed"] = False
        result["checks"]["search_returns_results"] = False
        result["checks"]["error"] = str(exc)

    return result


def run_smoke_tests(env: str) -> list[dict]:
    os.environ.setdefault("ENV", env)
    settings = AppSettings()
    customers = _get_customer_list()
    if not customers:
        logger.error("CUSTOMER_NAME_LIST is empty — nothing to test")
        sys.exit(1)

    results = []
    for customer in customers:
        index_name = f"db-{customer}"
        logger.info("Checking index '%s' ...", index_name)
        result = _check_index(settings, index_name)
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        logger.info("  %s  doc_count=%s", status, result["checks"].get("document_count", "N/A"))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test AI Search indexes")
    parser.add_argument("--ENV", type=str, required=True)
    args = parser.parse_args()

    results = run_smoke_tests(args.ENV)
    print(json.dumps(results, indent=2))

    if not all(r["passed"] for r in results):
        logger.error("Smoke tests FAILED")
        sys.exit(1)

    logger.info("All smoke tests PASSED")


if __name__ == "__main__":
    main()
