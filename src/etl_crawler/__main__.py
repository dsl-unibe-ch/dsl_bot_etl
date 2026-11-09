"""CLI entrypoint: ``python -m etl_crawler run --customer bnf [--steps crawl,extract]``."""

import argparse
import logging
from pathlib import Path

from src.etl_crawler.pipeline import (
    STEP_REGISTRY,
    run_pipeline,
    run_pipeline_for_enabled_customers,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)

logging.getLogger("pdfminer").setLevel(logging.WARNING)
logging.getLogger("pdfminer.psparser").setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="etl_crawler",
        description="Run the ETL crawler pipeline.",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser(
        "run", help="Execute pipeline steps for one customer"
    )
    run_parser.add_argument(
        "--customer",
        required=True,
        help="Customer id (must match a registry container customer-registry-<id>).",
    )
    run_parser.add_argument(
        "--steps",
        default=None,
        help=f"Comma-separated list of steps to run (default: all). Available: {', '.join(STEP_REGISTRY)}",
    )
    run_parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Explicit data directory (default: data/<customer>/<timestamp>).",
    )
    run_parser.add_argument(
        "--local-crawl-rules",
        action="store_true",
        help=(
            "Use the local customer_configs/<customer>.yml for crawl rules instead of "
            "the registry blob. Dev/test only."
        ),
    )

    run_all_parser = subparsers.add_parser(
        "run-all",
        help="Execute the pipeline for every ETL_ENABLED customer in the registry",
    )
    run_all_parser.add_argument(
        "--steps",
        default=None,
        help=f"Comma-separated list of steps to run (default: all). Available: {', '.join(STEP_REGISTRY)}",
    )

    args = parser.parse_args()

    if args.command == "run":
        steps = args.steps.split(",") if args.steps else None
        run_pipeline(
            customer_name=args.customer,
            steps=steps,
            data_dir=args.data_dir,
            use_local_crawl_rules=args.local_crawl_rules,
        )
    elif args.command == "run-all":
        steps = args.steps.split(",") if args.steps else None
        run_pipeline_for_enabled_customers(steps=steps)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
