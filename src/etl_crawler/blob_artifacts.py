"""Utilities for uploading ETL run artifacts to Azure Blob Storage."""

from __future__ import annotations

import logging
from pathlib import Path

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient

logger = logging.getLogger(__name__)


class ETLArtifactUploader:
    """Upload ETL output files to a blob container with run-scoped paths."""

    def __init__(self, connection_string: str, container_name: str, run_prefix: str) -> None:
        self._container_name = container_name
        self._run_prefix = run_prefix.strip("/")
        self._service = BlobServiceClient.from_connection_string(connection_string)
        self._container = self._service.get_container_client(container_name)
        self._ensure_container_exists()
        self._uploaded_file_state: dict[str, tuple[int, int]] = {}

    def _ensure_container_exists(self) -> None:
        """Create artifact container if it does not already exist."""
        try:
            self._container.create_container()
            logger.info("Created artifact container '%s'.", self._container_name)
        except ResourceExistsError:
            logger.info("Artifact container '%s' already exists.", self._container_name)

    def sync_run_outputs(self, data_dir: Path) -> None:
        """Upload all files in the run directory that are new or changed."""
        if not data_dir.exists():
            return

        for path in sorted(data_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(data_dir).as_posix()
            stat = path.stat()
            current_state = (stat.st_mtime_ns, stat.st_size)
            if self._uploaded_file_state.get(rel) == current_state:
                continue

            blob_path = f"{self._run_prefix}/{rel}"
            with path.open("rb") as fh:
                self._container.upload_blob(name=blob_path, data=fh, overwrite=True)

            self._uploaded_file_state[rel] = current_state
            logger.info(
                "Uploaded artifact %s to container %s as %s",
                rel,
                self._container_name,
                blob_path,
            )
