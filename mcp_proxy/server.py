"""
MCP Proxy Server using MCP Server SDK

Creates an MCP server that proxies to upstream MCP server with output summarization.
Uses MCP's Server SDK to properly handle the StreamableHTTP protocol.
"""

import asyncio
import json
import logging
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from openai import AsyncOpenAI


logger = logging.getLogger(__name__)


class MCPProxyServer:
    """MCP Proxy that bridges to upstream MCP server with summarization."""

    def __init__(
        self,
        upstream_url: str,
        llm_base_url: str | None,
        llm_api_key: str,
        llm_model: str,
        tool_rules: dict[str, Any],
    ):
        self.upstream_url = upstream_url
        self.llm_model = llm_model
        self.tool_rules = tool_rules

        # Initialize LLM client for summarization
        self.llm_client = AsyncOpenAI(
            base_url=llm_base_url,
            api_key=llm_api_key,
            timeout=30.0,
        ) if llm_base_url else None

        # MCP server instance
        self.server = Server("mcp-proxy")

        # Upstream connection - will be set up during server lifecycle
        self.upstream_session: ClientSession | None = None
        self.upstream_context = None

        # Register server handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register MCP server handlers."""

        @self.server.list_tools()
        async def list_tools() -> list[types.Tool]:
            """List tools from upstream."""
            if not self.upstream_session:
                return []

            result = await self.upstream_session.list_tools()
            return result.tools

        @self.server.call_tool()
        async def call_tool(
            name: str,
            arguments: dict[str, Any]
        ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
            """Proxy tool calls to upstream with summarization."""
            if not self.upstream_session:
                raise RuntimeError("Not connected to upstream")

            logger.info("Proxying tool call: %s", name)

            # Call upstream tool
            result = await self.upstream_session.call_tool(name, arguments)

            # Apply summarization if configured
            rule = self.tool_rules.get(name, {})
            if rule.get("enabled", False) and self.llm_client:
                summarized_content = await self._summarize_output(name, result, rule)
                return [types.TextContent(type="text", text=summarized_content)]

            # Return upstream result as-is
            return result.content

    async def connect_upstream(self):
        """Connect to upstream MCP server."""
        logger.info("Connecting to upstream: %s", self.upstream_url)

        # Start upstream connection
        self.upstream_context = streamablehttp_client(self.upstream_url)
        read_stream, write_stream, get_session_id = await self.upstream_context.__aenter__()

        self.upstream_session = ClientSession(read_stream, write_stream)
        await self.upstream_session.__aenter__()

        # Initialize MCP session (important!)
        init_result = await self.upstream_session.initialize()
        logger.info("MCP session initialized: protocol=%s", init_result.protocolVersion)

        # List available tools
        result = await self.upstream_session.list_tools()
        logger.info("Connected to upstream, found %d tools", len(result.tools))

        for tool in result.tools:
            logger.info("  - %s", tool.name)

    async def disconnect_upstream(self):
        """Disconnect from upstream."""
        if self.upstream_session:
            await self.upstream_session.__aexit__(None, None, None)

        if self.upstream_context:
            await self.upstream_context.__aexit__(None, None, None)

        logger.info("Disconnected from upstream")

    async def _summarize_output(
        self,
        tool_name: str,
        tool_result: types.CallToolResult,
        rule: dict[str, Any]
    ) -> str:
        """Summarize tool output using LLM."""
        max_tokens = rule.get("max_tokens", 8000)
        preservation = rule.get("preservation_instruction", "")

        # Extract text content from result
        text_parts = []
        for content_item in tool_result.content:
            if isinstance(content_item, types.TextContent):
                text_parts.append(content_item.text)

        output_str = "\n".join(text_parts)

        # Check if already small enough (rough: 1 token ≈ 4 chars)
        if len(output_str) // 4 <= max_tokens:
            return output_str

        logger.info("Summarizing %s output: %d chars", tool_name, len(output_str))

        prompt = f"""Summarize this tool output to fit within {max_tokens} tokens.

Tool: {tool_name}

Preservation Requirements:
{preservation}

Output to summarize:
{output_str}

Provide concise summary:"""

        response = await self.llm_client.chat.completions.create(
            model=self.llm_model,
            messages=[
                {"role": "system", "content": "Summarize tool outputs preserving key information."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=max_tokens,
        )

        summary = response.choices[0].message.content or output_str
        logger.info("Summarized: %d -> %d chars", len(output_str), len(summary))
        return summary.strip()

    def get_server(self) -> Server:
        """Return the MCP server instance."""
        return self.server


async def create_proxy_server(
    upstream_url: str,
    llm_base_url: str | None,
    llm_api_key: str,
    llm_model: str,
    tool_rules: dict[str, Any],
) -> MCPProxyServer:
    """Create and initialize proxy server."""
    proxy = MCPProxyServer(
        upstream_url=upstream_url,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        tool_rules=tool_rules,
    )

    await proxy.connect_upstream()
    return proxy