"""Configuration for Stellarbridge MCP server."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Server configuration loaded from environment variables."""

    # Stellarbridge API base URL (no trailing slash, no /api/v1 suffix)
    # Env: STELLARBRIDGE_API_URL
    api_url: str = "http://localhost:8080"

    # API key sent as X-API-Key on every request (not Authorization: Bearer)
    # Env: STELLARBRIDGE_API_KEY
    api_key: str = ""

    # Optional pre-supplied JWT token (skips /auth exchange)
    # Env: STELLARBRIDGE_JWT_TOKEN
    jwt_token: str = ""

    # HTTP timeout in seconds for API calls
    # Env: STELLARBRIDGE_HTTP_TIMEOUT
    http_timeout: float = 30.0

    model_config = {"env_prefix": "STELLARBRIDGE_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
