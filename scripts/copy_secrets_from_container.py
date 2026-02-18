from pathlib import Path
from src.etl_crawler.config import ETLSettings
from azure.storage.blob import BlobServiceClient
import logging
import argparse

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("Fetching Secrets from Container")
logger.setLevel(logging.DEBUG)
logger.propagate = False
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
logger.addHandler(handler)


def copy_secrets_from_container(etl_settings: ETLSettings, env: str):
    blob_service_client = BlobServiceClient.from_connection_string(
        etl_settings.AZURE_STORAGE_ACCOUNT_PRIMARY_CONNECTION_STRING
    )
    container_client = blob_service_client.get_container_client(
        container=etl_settings.AZURE_CONTAINER_STORAGE_SECRETS_NAME
    )
    remote_env_file = f".env.{env}"
    local_env_file = f".env.{env}.app"

    for blob in container_client.list_blobs():
        if blob.name == remote_env_file:
            blob_client = container_client.get_blob_client(blob=blob.name)
            data = blob_client.download_blob().readall()
            Path(local_env_file).write_bytes(data)
            logger.info(f"Downloaded {blob.name} -> {local_env_file}")
            return

    raise FileNotFoundError(
        f"{remote_env_file} not found in container {etl_settings.AZURE_CONTAINER_STORAGE_SECRETS_NAME}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch secrets from container")
    parser.add_argument("--ENV", type=str, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    etl_settings = ETLSettings()
    copy_secrets_from_container(etl_settings, env=args.ENV)


if __name__ == "__main__":
    main()