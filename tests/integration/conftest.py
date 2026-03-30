"""Shared fixtures for integration tests (real MCP stdio subprocess + HTTP mock API).

Integration tests require ``STELLARBRIDGE_API_KEY`` and ``STELLARBRIDGE_API_URL`` for the MCP
server process. The :func:`stellarbridge_api_env` fixture always injects both (mock URL from
``pytest-httpserver`` plus a deterministic test API key). Session defaults below ensure the
pytest process also has sensible values if anything reads :class:`stellarbridge_mcp.config.Settings`
before or outside a test case.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

_INTEGRATION_DEFAULT_API_KEY = "integration-test-api-key"
# Placeholder base URL for the test runner only; each test’s MCP subprocess gets the real mock URL.
_INTEGRATION_PLACEHOLDER_API_URL = "http://127.0.0.1:9"


@pytest.fixture(scope="session", autouse=True)
def _stellarbridge_env_defaults_for_integration_session() -> None:
    """Set STELLARBRIDGE_* in the pytest process when unset (CI, minimal shells, ``task``)."""
    os.environ.setdefault("STELLARBRIDGE_API_KEY", _INTEGRATION_DEFAULT_API_KEY)
    os.environ.setdefault("STELLARBRIDGE_API_URL", _INTEGRATION_PLACEHOLDER_API_URL)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def stellarbridge_api_env(httpserver: HTTPServer, repo_root: Path) -> Iterator[dict[str, str]]:
    """Environment for spawning the MCP server: mock API base URL + API key (both required)."""
    base = httpserver.url_for("/").rstrip("/")
    env = {
        **os.environ,
        "STELLARBRIDGE_API_URL": base,
        # Always use the integration key for the MCP child (never a developer’s real key).
        "STELLARBRIDGE_API_KEY": _INTEGRATION_DEFAULT_API_KEY,
        "STELLARBRIDGE_HTTP_TIMEOUT": "10",
    }
    assert env["STELLARBRIDGE_API_URL"].startswith("http")
    assert env["STELLARBRIDGE_API_KEY"], "STELLARBRIDGE_API_KEY must be non-empty"
    yield env
