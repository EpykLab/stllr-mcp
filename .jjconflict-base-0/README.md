# stellarbridge-mcp

[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for the **Stellarbridge** API: Drive (VFS), file transfers, upload requests, projects, and audit logs. Built with [FastMCP](https://github.com/jlowin/fastmcp) and Python 3.13+.

## Requirements

- Python **3.13+**
- [uv](https://docs.astral.sh/uv/) (recommended) or another PEP 517 installer

## Install

```bash
uv sync
```

Install with dev dependencies (tests, linters):

```bash
uv sync --group dev
```

## Configuration

All settings use the prefix **`STELLARBRIDGE_`** (see `src/stellarbridge_mcp/config.py`).

| Variable | Purpose |
|----------|---------|
| `STELLARBRIDGE_API_URL` | Stellarbridge API **base URL** (no `/api/v1` suffix). Default: `http://localhost:8080` |
| `STELLARBRIDGE_API_KEY` | API key sent as `X-API-Key` on requests |
| `STELLARBRIDGE_JWT_TOKEN` | Optional; if set, skips auth exchange |
| `STELLARBRIDGE_HTTP_TIMEOUT` | HTTP timeout in seconds (default: `30`) |

## Run the server

**Installed script (stdio, default):**

```bash
uv run stellarbridge-mcp
```

**Module form:**

```bash
uv run python -m stellarbridge_mcp
```

The server speaks MCP over **stdio** unless you configure FastMCP for another transport.

### Example: MCP client over stdio

```json
{
  "mcpServers": {
    "stellarbridge": {
      "command": "uv",
      "args": ["run", "python", "-m", "stellarbridge_mcp"],
      "cwd": "/path/to/stllr-mcp",
      "env": {
        "STELLARBRIDGE_API_URL": "https://your-api-host.example.com",
        "STELLARBRIDGE_API_KEY": "your-api-key"
      }
    }
  }
}
```

Adjust `cwd` to your clone of this repository (or use a global install and omit `cwd` if `stellarbridge-mcp` is on `PATH`).

## Tool surface

Tools are namespaced when mounted on the root server, for example:

- **`drive_*`** — list/get/create/move Drive objects, upload/download URLs, sharing, policies  
- **`transfers_*`** — transfers, multipart upload helpers  
- **`requests_*`** — file upload requests  
- **`projects_*`** — projects  
- **`audit_*`** — audit log queries  

Use your MCP client’s **tools/list** to see exact names and schemas for your build.

## Development

| Task | Command |
|------|---------|
| Run unit tests | `uv run pytest` (integration live tests skip without opt-in env) |
| Mock MCP integration tests | `uv run pytest tests/integration -v` or `task test-integration` |
| Live API smoke tests | See [tests/README.md](tests/README.md) (`STELLARBRIDGE_LIVE_API=1`, real URL + key) |
| Lint | `uv run ruff check` |
| Typecheck | `uv run mypy src` |

**Task** shortcuts (requires [Task](https://taskfile.dev/)): `task build`, `task run`, `task test-integration`, `task test-integration-live`, `task inspector`.

Full testing documentation: **[tests/README.md](tests/README.md)**.

## Project layout

```
src/stellarbridge_mcp/   # Package: server, HTTP client, tools by domain
tests/                   # Unit + integration tests (see tests/README.md)
```
