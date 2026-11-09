"""HTTP Basic Auth credential resolution for password-protected crawl targets."""

import os

from dotenv import dotenv_values

# Matches ETLSettings.model_config's env_file -- real env vars (e.g. Container
# App secrets in production) take priority; this is a local-dev-only fallback,
# since pydantic-settings parses .env.etl into ETLSettings without exporting it
# to os.environ.
_ETL_ENV_FILE = ".env.etl"


def _lookup_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    return dotenv_values(_ETL_ENV_FILE).get(name) or None


def resolve_basic_auth(customer_config: dict) -> tuple[str, str, str] | None:
    """Resolve (domain, username, password) for a basic_auth-protected domain.

    ``customer_config["basic_auth"]`` holds only env var *names*
    (``username_env``/``password_env``), never literal credentials -- crawl configs
    are either committed to git (local dev YAML) or stored in the customer registry,
    neither of which should carry secrets. Returns None if basic_auth isn't configured.
    """
    basic_auth = customer_config.get("basic_auth")
    if not basic_auth:
        return None

    domain = basic_auth.get("domain")
    username_env = basic_auth.get("username_env")
    password_env = basic_auth.get("password_env")
    if not domain or not username_env or not password_env:
        raise ValueError(
            "basic_auth config must specify 'domain', 'username_env' and 'password_env'"
        )

    username = _lookup_env(username_env)
    password = _lookup_env(password_env)
    if not username or not password:
        raise RuntimeError(
            f"basic_auth configured for domain '{domain}' but env var(s) "
            f"'{username_env}'/'{password_env}' are not set"
        )
    return domain, username, password
