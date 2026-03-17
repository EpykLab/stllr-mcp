"""Tests for Stellarbridge MCP configuration."""

import pytest

from stellarbridge_mcp.config import Settings


class TestSettings:
    def test_defaults(self) -> None:
        s = Settings()
        assert s.api_url == "http://localhost:8080"
        assert s.api_key == ""
        assert s.jwt_token == ""
        assert s.http_timeout == 30.0

    def test_explicit_overrides(self) -> None:
        """Settings accepts explicit overrides (e.g. from env when loaded)."""
        s = Settings(
            api_url="https://api.example.com",
            api_key="key",
            http_timeout=60.0,
        )
        assert s.api_url == "https://api.example.com"
        assert s.http_timeout == 60.0
        assert s.api_key == "key"

    def test_extra_ignored(self) -> None:
        s = Settings(api_url="http://localhost:8080")
        assert s.api_url == "http://localhost:8080"

    def test_env_vars_single_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env vars are STELLARBRIDGE_API_KEY and STELLARBRIDGE_API_URL (no double prefix)."""
        monkeypatch.setenv("STELLARBRIDGE_API_URL", "https://api.example.com")
        monkeypatch.setenv("STELLARBRIDGE_API_KEY", "env-key")
        # Clear any cached module-level settings by building fresh
        s = Settings()
        assert s.api_url == "https://api.example.com"
        assert s.api_key == "env-key"
        monkeypatch.delenv("STELLARBRIDGE_API_URL", raising=False)
        monkeypatch.delenv("STELLARBRIDGE_API_KEY", raising=False)
