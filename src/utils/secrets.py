"""Utility for fetching secrets from Infisical at runtime."""

import os
import threading
import time
from typing import Optional

import requests

from src.utils.logging_config import get_logger


logger = get_logger(__name__)

_cache: dict[str, tuple[str, float]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL_SECONDS = 300  # 5 minutes


def get_infisical_secret(
    secret_name: str,
    *,
    environment: str = "prod",
    workspace_id: Optional[str] = None,
    infisical_url: Optional[str] = None,
    infisical_token: Optional[str] = None,
) -> str:
    """
    Fetch a secret from Infisical by name.

    Uses an in-memory cache with 5-minute TTL to avoid repeated HTTP calls.

    Args:
        secret_name: Name of the secret (e.g. "GITHUB_TOKEN")
        environment: Infisical environment slug (default: "prod")
        workspace_id: Infisical workspace ID (defaults to env INFISICAL_WORKSPACE_ID)
        infisical_url: Infisical API base URL (defaults to env INFISICAL_URL)
        infisical_token: Bearer token for auth (defaults to env INFISICAL_TOKEN)

    Returns:
        The secret value string.

    Raises:
        ValueError: If required configuration is missing.
        RuntimeError: If the API call fails.
    """
    cache_key = f"{environment}:{secret_name}"

    with _cache_lock:
        if cache_key in _cache:
            value, fetched_at = _cache[cache_key]
            if time.time() - fetched_at < _CACHE_TTL_SECONDS:
                return value

    url = infisical_url or os.environ.get("INFISICAL_URL", "http://localhost:4938")
    token = infisical_token or os.environ.get("INFISICAL_TOKEN")
    ws_id = workspace_id or os.environ.get(
        "INFISICAL_WORKSPACE_ID", "abb3588b-8c8f-46bf-a802-964b4f34a056"
    )

    if not token:
        raise ValueError(
            "INFISICAL_TOKEN is required. Set it as an environment variable or pass infisical_token."
        )

    api_url = f"{url.rstrip('/')}/api/v3/secrets/raw/{secret_name}"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"workspaceId": ws_id, "environment": environment}

    try:
        resp = requests.get(api_url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        secret_value = data["secret"]["secretValue"]

        with _cache_lock:
            _cache[cache_key] = (secret_value, time.time())

        logger.debug("infisical_secret_fetched", secret_name=secret_name, environment=environment)
        return secret_value

    except requests.HTTPError as e:
        error_msg = f"Infisical API error fetching '{secret_name}': {e.response.status_code} {e.response.text}"
        logger.error("infisical_fetch_failed", secret_name=secret_name, error=error_msg)
        raise RuntimeError(error_msg) from e
    except (requests.ConnectionError, requests.Timeout) as e:
        error_msg = f"Cannot connect to Infisical at {url}: {e}"
        logger.error("infisical_connection_failed", url=url, error=str(e))
        raise RuntimeError(error_msg) from e
    except KeyError as e:
        error_msg = f"Unexpected Infisical response format for '{secret_name}'"
        logger.error("infisical_parse_failed", secret_name=secret_name, error=error_msg)
        raise RuntimeError(error_msg) from e
