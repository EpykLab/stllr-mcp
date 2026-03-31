"""Smoke tests for the Stellarbridge MCP server."""

from unittest.mock import patch

from stellarbridge_mcp import server


class TestServerModule:
    def test_mcp_app_exists(self) -> None:
        assert server.mcp is not None
        assert server.mcp.name == "stellarbridge"

    def test_main_calls_run(self) -> None:
        with patch.object(server.mcp, "run") as mock_run:
            server.main()
            mock_run.assert_called_once()
