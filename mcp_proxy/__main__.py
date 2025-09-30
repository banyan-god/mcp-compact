"""
MCP Proxy Server entry point

Usage:
    MCP_PROXY_CONFIG_FILE=test_proxy_config.json \
    MCP_UPSTREAM_URL=http://192.168.1.164:8931/mcp \
    BASE_URL=http://192.168.1.164:8000/v1 \
    API_KEY=EMPTY \
    MODEL_NAME=openai/gpt-oss-120b \
    python -m mcp_proxy --host localhost --port 8009
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from .server import create_proxy_server


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Main entry point."""
    # Load .env file if it exists
    load_dotenv()

    parser = argparse.ArgumentParser(description="MCP Proxy Server")
    parser.add_argument("--host", default="localhost", help="Server host")
    parser.add_argument("--port", type=int, default=8009, help="Server port")
    parser.add_argument("--log-level", default="INFO", help="Log level")
    args = parser.parse_args()

    # Set log level
    logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))

    # Load configuration from environment
    upstream_url = os.getenv("MCP_UPSTREAM_URL")
    if not upstream_url:
        logger.error("MCP_UPSTREAM_URL environment variable required")
        sys.exit(1)

    llm_base_url = os.getenv("BASE_URL")
    llm_api_key = os.getenv("API_KEY", "EMPTY")
    llm_model = os.getenv("MODEL_NAME", "openai/gpt-oss-120b")
    config_file = os.getenv("MCP_PROXY_CONFIG_FILE")

    # Load tool rules
    tool_rules = {}
    if config_file and os.path.exists(config_file):
        with open(config_file) as f:
            data = json.load(f)
            tool_rules = data.get("tool_rules", {})
        logger.info("Loaded %d tool rules from %s", len(tool_rules), config_file)

    logger.info("Starting MCP Proxy Server...")
    logger.info("  Proxy: http://%s:%d", args.host, args.port)
    logger.info("  Upstream: %s", upstream_url)
    if llm_base_url:
        logger.info("  LLM: %s at %s", llm_model, llm_base_url)
    logger.info("  Compaction rules: %s", ", ".join(tool_rules.keys()) or "none")

    # Create proxy server
    try:
        proxy = await create_proxy_server(
            upstream_url=upstream_url,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            tool_rules=tool_rules,
        )
    except Exception as e:
        logger.error("Failed to create proxy server: %s", e, exc_info=True)
        sys.exit(1)

    # Create session manager
    mcp_server = proxy.get_server()
    session_manager = StreamableHTTPSessionManager(mcp_server)

    # Run server with uvicorn
    logger.info("MCP Proxy Server running on http://%s:%d", args.host, args.port)

    @asynccontextmanager
    async def lifespan(app):
        """Lifespan context for session manager."""
        async with session_manager.run():
            yield

    async def app(scope, receive, send):
        """ASGI application."""
        await session_manager.handle_request(scope, receive, send)

    # Start session manager and run server
    async with session_manager.run():
        config = uvicorn.Config(
            app=app,
            host=args.host,
            port=args.port,
            log_level=args.log_level.lower(),
        )
        server = uvicorn.Server(config)
        await server.serve()


if __name__ == "__main__":
    asyncio.run(main())