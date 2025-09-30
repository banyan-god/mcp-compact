# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

MCP Compact is an MCP (Model Context Protocol) proxy server that provides intelligent output compaction using LLM-based summarization. It acts as a transparent middleware between MCP clients and upstream MCP servers, intercepting tool call responses and applying configurable summarization rules to reduce context window usage by up to 97%.

## Architecture

The proxy operates in three layers:

1. **MCP Server Layer** (`mcp_proxy/__main__.py`): Uvicorn ASGI server with StreamableHTTPSessionManager that handles client connections
2. **Proxy Orchestration** (`mcp_proxy/server.py`): Core `MCPProxyServer` class that bridges upstream connections and applies summarization
3. **LLM Summarization**: OpenAI-compatible API client that compresses tool outputs based on per-tool rules

**Critical implementation detail**: The proxy maintains a `ClientSession` to the upstream MCP server. This session MUST be initialized via `await self.upstream_session.initialize()` (server.py:102) to complete the MCP protocol handshake before proxying tool calls.

## Development Commands

### Environment Setup
```bash
python3.12 -m venv .venv
source .venv/bin/activate  # or .venv/bin/activate.fish, etc.
pip install -r requirements.txt
```

### Running the Proxy
Configuration via environment variables (automatically loaded from `.env` file):
```bash
python -m mcp_proxy --host localhost --port 8009
```

Required environment variables:
- `MCP_UPSTREAM_URL` - Upstream MCP server endpoint (e.g., `http://localhost:8931/mcp`)
- `BASE_URL` - LLM API endpoint for summarization (optional; if omitted, no summarization occurs)

Optional environment variables:
- `MCP_PROXY_CONFIG_FILE` - Path to tool rules config (default: searches for `config.json`)
- `API_KEY` - LLM API key (default: "EMPTY")
- `MODEL_NAME` - LLM model name (default: "openai/gpt-oss-120b")

CLI flags:
- `--host` - Server bind address (default: "localhost")
- `--port` - Server port (default: 8009)
- `--log-level` - Log verbosity (default: "INFO")

### Configuration Files

Tool summarization rules are defined in JSON format (see `config.example.json`):
```json
{
  "tool_rules": {
    "browser_snapshot": {
      "enabled": true,
      "max_tokens": 8000,
      "preservation_instruction": "Preserve all clickable elements..."
    }
  }
}
```

Copy `config.example.json` → `config.json` and customize per-tool rules. The `test_proxy_config.json` file is a minimal fixture for testing.

## Code Structure & Key Components

### `mcp_proxy/server.py`

**`MCPProxyServer.__init__()`**: Initializes OpenAI client (conditionally, only if `llm_base_url` is provided) and registers MCP server handlers

**`MCPProxyServer._register_handlers()`**: Registers two MCP handlers:
- `@server.list_tools()` - Proxies tool list from upstream
- `@server.call_tool()` - Proxies tool calls with optional summarization (server.py:67-88)

**`MCPProxyServer.connect_upstream()`**: Establishes connection to upstream via `streamablehttp_client()` and initializes the MCP session. **Critical**: Must call `await self.upstream_session.initialize()` to complete handshake.

**`MCPProxyServer._summarize_output()`**: LLM-based summarization with fallback behavior:
- Returns original output if already under token limit
- Returns original output if LLM client is None (BASE_URL not configured)
- Catches all exceptions and returns original output on API failures (server.py:163-179)

### `mcp_proxy/__main__.py`

**`main()`**: Entry point that:
1. Loads `.env` file via `python-dotenv`
2. Parses CLI arguments
3. Validates required environment variables (exits if `MCP_UPSTREAM_URL` missing)
4. Loads tool rules from config file
5. Creates proxy server via `create_proxy_server()`
6. Runs uvicorn server with `StreamableHTTPSessionManager` context manager

**Session manager lifecycle**: The code uses `async with session_manager.run():` to manage the MCP session lifecycle. Previously had a duplicate context manager bug (see BUG_FIXES.md).

## Testing

No automated test suite exists yet. For manual testing:

1. **Without LLM (pass-through mode)**:
   ```bash
   MCP_UPSTREAM_URL=http://localhost:8931/mcp python -m mcp_proxy
   ```
   Should proxy tools without summarization.

2. **With LLM summarization**:
   ```bash
   MCP_PROXY_CONFIG_FILE=config.json \
   MCP_UPSTREAM_URL=http://localhost:8931/mcp \
   BASE_URL=http://localhost:8000/v1 \
   API_KEY=test-key \
   MODEL_NAME=openai/gpt-oss-120b \
   python -m mcp_proxy
   ```

3. **Test with MCP client**:
   Point your MCP client to `http://localhost:8009/mcp` instead of the upstream server URL.

## Error Handling Patterns

The proxy implements graceful degradation:
- **No LLM configured** (`BASE_URL` not set): Proxy works in pass-through mode (server.py:43)
- **LLM API failures**: Catches exceptions and returns original output (server.py:177-179)
- **Upstream connection failures**: Exits with error code 1 at startup (__main__.py:84-85)

## Configuration & Secrets

- `.env` file is auto-loaded via `python-dotenv` (added September 2025)
- Never commit real credentials; use `.env.example` for templates
- The proxy defaults to "EMPTY" for `API_KEY` to support development with permissive LLM servers

## Dependencies

Core dependencies (requirements.txt):
- `mcp>=1.0.0` - Official MCP Python SDK (client and server)
- `openai>=1.0.0` - OpenAI-compatible LLM client
- `uvicorn>=0.27.0` - ASGI server
- `httpx>=0.26.0` - HTTP client (used by MCP SDK)
- `python-dotenv>=0.21.0` - Environment variable loading from `.env`
