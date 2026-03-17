"""Tests for Stellarbridge MCP configuration."""

from stellarbridge_mcp.config import Settings


class TestSettings:
    def test_defaults(self) -> None:
        s = Settings()
        assert s.stellarbridge_api_url == "http://localhost:8080"
        assert s.stellarbridge_api_key == ""
        assert s.stellarbridge_jwt_token == ""
        assert s.http_timeout == 30.0

    def test_explicit_overrides(self) -> None:
        """Settings accepts explicit overrides (e.g. from env when loaded)."""
        s = Settings(
            stellarbridge_api_url="https://api.example.com",
            stellarbridge_api_key="key",
            http_timeout=60.0,
        )
        assert s.stellarbridge_api_url == "https://api.example.com"
        assert s.http_timeout == 60.0
        assert s.stellarbridge_api_key == "key"

    def test_extra_ignored(self) -> None:
        s = Settings(stellarbridge_api_url="http://localhost:8080")
        assert s.stellarbridge_api_url == "http://localhost:8080"
