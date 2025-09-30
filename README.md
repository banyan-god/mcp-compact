# MCP Compact

A Model Context Protocol (MCP) proxy server that provides intelligent output compaction using LLM-based summarization. Reduces context window usage by up to 97% while preserving essential information.

## Features

- **Transparent MCP Proxy**: Drop-in replacement for any MCP server
- **Smart Summarization**: LLM-powered output compaction with configurable rules
- **StreamableHTTP Protocol**: Full support for MCP's streaming transport
- **Zero Modification**: Works with existing MCP clients without code changes
- **Production Ready**: Built on official MCP Python SDK

## Architecture

```
MCP Client → MCP Compact (localhost:8009) → Upstream MCP Server
              ↓ (intercept & summarize)
              LLM Summarizer
```

The proxy sits between your MCP client and upstream MCP server, intercepting tool call responses and applying intelligent summarization based on configurable rules.

## Quick Start

### Installation

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configuration

1. Copy the example config:
```bash
cp config.example.json config.json
```

2. Edit `config.json` to configure which tools should be summarized and how.

### Running

```bash
MCP_PROXY_CONFIG_FILE=config.json \
MCP_UPSTREAM_URL=http://your-mcp-server:8931/mcp \
BASE_URL=http://your-llm-server:8000/v1 \
API_KEY=your-api-key \
MODEL_NAME=your-model \
python -m mcp_proxy --host localhost --port 8009
```

### Testing

Point your MCP client to `http://localhost:8009/mcp` instead of the upstream server:

```bash
MCP_SERVER_URL=http://localhost:8009/mcp python your_client.py
```

## Configuration

The `config.json` file defines summarization rules per tool:

```json
{
  "tool_rules": {
    "browser_snapshot": {
      "enabled": true,
      "max_tokens": 8000,
      "preservation_instruction": "Preserve all clickable elements, form fields, and interactive components. Maintain page structure and navigation elements."
    },
    "browser_navigate": {
      "enabled": true,
      "max_tokens": 6000,
      "preservation_instruction": "Keep all links, buttons, and navigation elements. Preserve page title and main content structure."
    }
  }
}
```

### Rule Parameters

- **enabled**: Whether to apply summarization to this tool
- **max_tokens**: Maximum tokens for summarized output (rough: 1 token ≈ 4 chars)
- **preservation_instruction**: Guidance to LLM on what information to preserve

## Environment Variables

### Required

- `MCP_UPSTREAM_URL` - Upstream MCP server endpoint (e.g., `http://192.168.1.164:8931/mcp`)
- `BASE_URL` - LLM API endpoint for summarization (e.g., `http://192.168.1.164:8000/v1`)

### Optional

- `MCP_PROXY_CONFIG_FILE` - Path to config file (default: searches for `config.json`)
- `API_KEY` - LLM API key (default: "EMPTY")
- `MODEL_NAME` - LLM model name (default: "openai/gpt-oss-120b")
- `--host` - Server host (default: "localhost")
- `--port` - Server port (default: 8009)
- `--log-level` - Log level (default: "INFO")

## Example Usage

### Browser Automation Tool Compaction

Original output: 114,723 characters
Compacted output: 3,084 characters (97.3% reduction)

The proxy identified this was a `browser_navigate` call, applied the configured summarization rule, and reduced the output while preserving all clickable elements and navigation structure.

### Real-world Impact

In production testing with web research agents:
- Average tool output: 50,000-100,000 characters
- After compaction: 3,000-5,000 characters
- Context savings: 94-97%
- Quality retention: High (configurable per tool)

## Development

### Project Structure

```
mcp-compact/
├── mcp_proxy/
│   ├── __init__.py          # Package version
│   ├── __main__.py          # Entry point with session manager
│   └── server.py            # Core proxy logic
├── config.example.json      # Example configuration
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

### Key Implementation Details

The proxy uses:
- **MCP Client SDK**: `streamablehttp_client()` to connect upstream
- **MCP Server SDK**: `Server()` and `StreamableHTTPSessionManager` to serve clients
- **OpenAI Client**: For LLM-based summarization

Critical implementation note: The proxy calls `await session.initialize()` to complete the MCP handshake with the upstream server.

## Deployment

The proxy is designed for standalone deployment:

```bash
# Production deployment
docker build -t mcp-compact .
docker run -p 8009:8009 \
  -e MCP_UPSTREAM_URL=http://upstream:8931/mcp \
  -e BASE_URL=http://llm:8000/v1 \
  -e API_KEY=your-key \
  -e MODEL_NAME=your-model \
  mcp-compact
```

## Performance

- Latency: +2-5s per tool call (for LLM summarization)
- Throughput: Scales with upstream server and LLM capacity
- Memory: ~100MB base + LLM client overhead
- Context savings: 90-97% typical

The added latency is offset by reduced context in subsequent agent turns, resulting in faster overall workflow completion.

## License

[To be determined]

## Credits

Built using the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)