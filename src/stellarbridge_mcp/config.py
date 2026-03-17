"""Configuration for Stellarbridge MCP server."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Server configuration loaded from environment variables."""

    # Stellarbridge API base URL (no trailing slash, no /api/v1 suffix)
    stellarbridge_api_url: str = "http://localhost:8080"

    # API key used to authenticate with Stellarbridge (exchanged for JWT)
    stellarbridge_api_key: str = ""

    # Optional: pre-supply a JWT token directly (skips /auth exchange)
    stellarbridge_jwt_token: str = ""

    # HTTP timeout in seconds for API calls
    http_timeout: float = 30.0

    model_config = {"env_prefix": "STELLARBRIDGE_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
