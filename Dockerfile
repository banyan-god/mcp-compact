# MCP Compact - Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY mcp_proxy/ ./mcp_proxy/

# Copy default config (can be overridden with volume mount)
COPY config.example.json ./config.json

# Expose default port
EXPOSE 8009

# Environment variables with defaults
ENV MCP_PROXY_CONFIG_FILE=config.json
ENV HOST=0.0.0.0
ENV PORT=8009
ENV LOG_LEVEL=INFO

# Run the proxy server
CMD python -m mcp_proxy \
    --host ${HOST} \
    --port ${PORT} \
    --log-level ${LOG_LEVEL}