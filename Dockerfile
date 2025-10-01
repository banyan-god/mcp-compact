# MCP Compact - Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY mcp_proxy/ ./mcp_proxy/

# Copy default config and environment template
COPY config.example.json ./config.json
COPY test_proxy_config.json ./test_proxy_config.json
COPY .env.example ./.env

# Expose default port
EXPOSE 8002

# Environment variables with defaults
# Note: MCP_UPSTREAM_URL must be set via docker run -e or docker-compose
ENV MCP_PROXY_CONFIG_FILE=test_proxy_config.json
ENV HOST=0.0.0.0
ENV PORT=8002
ENV LOG_LEVEL=INFO

# Run the proxy server (JSON array format for proper signal handling)
CMD ["sh", "-c", "python -m mcp_proxy --host ${HOST} --port ${PORT} --log-level ${LOG_LEVEL}"]