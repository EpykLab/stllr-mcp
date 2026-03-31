"""Live API tests: opt-in only; never run against mocks by accident."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

_INTEGRATION_PLACEHOLDER_URL: Final = "http://127.0.0.1:9"
_INTEGRATION_PLACEHOLDER_KEY: Final = "integration-test-api-key"


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def real_stellarbridge_env() -> Iterator[dict[str, str]]:
    """Environment for the MCP child: real API URL and key (not mock placeholders)."""
    if not _truthy_env("STELLARBRIDGE_LIVE_API"):
        pytest.skip(
            "Live API tests are opt-in. Set STELLARBRIDGE_LIVE_API=1 and real "
            "STELLARBRIDGE_API_URL / STELLARBRIDGE_API_KEY."
        )
    url = os.environ.get("STELLARBRIDGE_API_URL", "").strip().rstrip("/")
    key = os.environ.get("STELLARBRIDGE_API_KEY", "").strip()
    if not url or not key:
        pytest.skip("STELLARBRIDGE_API_URL and STELLARBRIDGE_API_KEY must be set for live tests.")
    if url == _INTEGRATION_PLACEHOLDER_URL.rstrip("/"):
        pytest.skip(
            "Refusing live tests with placeholder STELLARBRIDGE_API_URL; "
            "point to a real API base (no /api/v1 suffix)."
        )
    if key == _INTEGRATION_PLACEHOLDER_KEY:
        pytest.skip(
            "Refusing live tests with placeholder STELLARBRIDGE_API_KEY; use a real API key."
        )
    timeout = os.environ.get("STELLARBRIDGE_HTTP_TIMEOUT", "120")
    env = {
        **os.environ,
        "STELLARBRIDGE_API_URL": url,
        "STELLARBRIDGE_API_KEY": key,
        "STELLARBRIDGE_HTTP_TIMEOUT": timeout,
    }
    yield env
