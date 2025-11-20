"""
MCP Proxy Server using MCP Server SDK

Creates an MCP server that proxies to upstream MCP server with output summarization.
Uses MCP's Server SDK to properly handle the StreamableHTTP protocol.
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, TypeVar

import tiktoken
import httpx
from mcp import types
from mcp.server import Server
from mcp.shared.context import RequestContext
from mcp.shared.exceptions import McpError
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from openai import AsyncOpenAI


logger = logging.getLogger(__name__)

T = TypeVar("T")


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
            timeout=60.0,
        ) if llm_base_url else None

        # Initialize tiktoken encoder for accurate token counting
        try:
            # Use cl100k_base encoding (GPT-4, GPT-3.5-turbo)
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            logger.warning("Failed to load tiktoken encoder, falling back to char estimation: %s", e)
            self.tokenizer = None

        # MCP server instance
        self.server = Server("mcp-proxy")

        # Upstream connection - will be set up during server lifecycle
        self.upstream_session: ClientSession | None = None
        self.upstream_context = None
        self._connection_lock = asyncio.Lock()

        # Register server handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register MCP server handlers."""

        @self.server.list_tools()
        async def list_tools() -> list[types.Tool]:
            """List tools from upstream."""
            async def _list(session: ClientSession) -> list[types.Tool]:
                result = await session.list_tools()
                return result.tools

            return await self._execute_with_reconnect("list_tools", _list)

        @self.server.call_tool()
        async def call_tool(
            name: str,
            arguments: dict[str, Any],
            ctx: RequestContext | None = None
        ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
            """Proxy tool calls to upstream with summarization."""
            if not self.upstream_session:
                raise RuntimeError("Not connected to upstream")

            logger.info("Proxying tool call: %s", name)

            async def _call_upstream(session: ClientSession) -> types.CallToolResult:
                return await session.call_tool(name, arguments)

            # Call upstream tool
            result = await self._execute_with_reconnect(f"call_tool:{name}", _call_upstream)

            # Apply summarization if configured
            rule = self.tool_rules.get(name, {})
            if rule.get("enabled", False) and self.llm_client:
                summarized_content = await self._summarize_output(
                    name, result, rule, context=ctx
                )
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
            self.upstream_session = None

        if self.upstream_context:
            await self.upstream_context.__aexit__(None, None, None)
            self.upstream_context = None

        logger.info("Disconnected from upstream")

    async def _reconnect_upstream(self, reason: str = "session failure", force: bool = False) -> None:
        """Reconnect to the upstream MCP server, guarding with a lock."""
        async with self._connection_lock:
            if self.upstream_session and not force:
                return

            logger.warning("Reconnecting to upstream (%s)", reason)
            await self.disconnect_upstream()
            await self.connect_upstream()

    async def _execute_with_reconnect(
        self,
        operation_name: str,
        operation: Callable[[ClientSession], Awaitable[T]],
    ) -> T:
        """Execute an upstream call and reconnect once on session errors."""
        for attempt in range(2):
            if not self.upstream_session:
                await self._reconnect_upstream("session missing")
                if not self.upstream_session:
                    continue

            session = self.upstream_session
            if not session:
                continue

            try:
                return await operation(session)
            except McpError as exc:
                if not self._should_reconnect(exc) or attempt == 1:
                    raise
                logger.info("Upstream session error during %s: %s", operation_name, exc)
                await self._reconnect_upstream(exc.error.message or operation_name, force=True)
            except httpx.HTTPError as exc:
                if attempt == 1:
                    raise
                logger.info("HTTP error during %s: %s", operation_name, exc)
                await self._reconnect_upstream("http error", force=True)

        raise RuntimeError(f"Failed to execute {operation_name} even after reconnect")

    @staticmethod
    def _should_reconnect(exc: McpError) -> bool:
        """Return True if the error indicates the upstream session closed."""
        if exc.error.code == types.CONNECTION_CLOSED:
            return True

        message = (exc.error.message or "").lower()
        return "session terminated" in message or "connection closed" in message

    async def _summarize_output(
        self,
        tool_name: str,
        tool_result: types.CallToolResult,
        rule: dict[str, Any],
        context: RequestContext | None = None
    ) -> str:
        """Summarize tool output using LLM with streaming support."""
        max_tokens = rule.get("max_tokens", 8000)
        preservation = rule.get("preservation_instruction", "")

        # Extract text content from result
        text_parts = []
        for content_item in tool_result.content:
            if isinstance(content_item, types.TextContent):
                text_parts.append(content_item.text)

        output_str = "\n".join(text_parts)

        # Use tiktoken for accurate token counting, fallback to estimation
        if self.tokenizer:
            try:
                estimated_tokens = len(self.tokenizer.encode(output_str))
            except Exception as e:
                logger.warning("tiktoken encoding failed, using char estimation: %s", e)
                estimated_tokens = len(output_str) // 2
        else:
            estimated_tokens = len(output_str) // 2

        logger.info(
            "Tool %s output: %d chars (%d tokens), max_tokens: %d, enabled: %s",
            tool_name, len(output_str), estimated_tokens, max_tokens, rule.get("enabled", False)
        )

        # Check if already small enough
        if estimated_tokens <= max_tokens:
            logger.info("Output is already within token limit, skipping summarization")
            return output_str

        # Ensure LLM client is available
        if not self.llm_client:
            logger.warning("LLM client not configured, returning original output for %s", tool_name)
            return output_str

        # Clip input to 128k tokens to prevent model context overflow
        max_input_tokens = 128000
        if estimated_tokens > max_input_tokens:
            logger.warning(
                "Input too large (%d tokens), clipping to %d tokens for %s",
                estimated_tokens, max_input_tokens, tool_name
            )
            if self.tokenizer:
                # Use tiktoken to clip precisely at token boundary
                tokens = self.tokenizer.encode(output_str)
                clipped_tokens = tokens[:max_input_tokens]
                output_str = self.tokenizer.decode(clipped_tokens) + "\n\n[... output truncated due to size ...]"
            else:
                # Fallback to char-based clipping
                max_input_chars = max_input_tokens * 2
                output_str = output_str[:max_input_chars] + "\n\n[... output truncated due to size ...]"

        logger.info("Summarizing %s output: %d chars -> target %d tokens", tool_name, len(output_str), max_tokens)

        # Send progress notification if context is available
        if context and context.session:
            try:
                await context.session.send_progress_notification(
                    progress_token=context.request_id,
                    progress=0.0,
                    total=1.0,
                    message=f"Starting summarization of {tool_name} output..."
                )
            except Exception as e:
                logger.debug("Failed to send progress notification: %s", e)

        prompt = f"""Summarize this tool output to fit within {max_tokens} tokens.

Tool: {tool_name}

Preservation Requirements:
{preservation}

Output to summarize:
{output_str}

Provide concise summary:"""

        try:
            # Use streaming API for LLM
            stream = await self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": "Summarize tool outputs preserving key information."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=max_tokens,
                stream=True,
            )

            summary_chunks = []
            total_chars = 0
            last_progress_update = 0

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    summary_chunks.append(content)
                    total_chars += len(content)

                    # Send progress updates periodically (every 500 chars)
                    if context and context.session and total_chars - last_progress_update > 500:
                        try:
                            # Estimate progress (capped at 90% until complete)
                            estimated_progress = min(0.9, total_chars / (max_tokens * 4))
                            await context.session.send_progress_notification(
                                progress_token=context.request_id,
                                progress=estimated_progress,
                                total=1.0,
                                message=f"Summarizing... ({total_chars} chars generated)"
                            )
                            last_progress_update = total_chars
                        except Exception as e:
                            logger.debug("Failed to send progress notification: %s", e)

            summary = "".join(summary_chunks) or output_str

            # Send final progress notification
            if context and context.session:
                try:
                    await context.session.send_progress_notification(
                        progress_token=context.request_id,
                        progress=1.0,
                        total=1.0,
                        message=f"Summarization complete: {len(output_str)} → {len(summary)} chars"
                    )
                except Exception as e:
                    logger.debug("Failed to send progress notification: %s", e)

            logger.info("Summarized: %d -> %d chars", len(output_str), len(summary))
            return summary.strip()
        except Exception as e:
            logger.error("Failed to summarize output for %s: %s", tool_name, e, exc_info=True)
            return output_str

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
