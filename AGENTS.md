# Repository Guidelines

## Project Structure & Module Organization
- `mcp_proxy/` contains the runtime: `server.py` holds the proxy orchestration and summarization pipeline, while `__main__.py` wires CLI arguments, environment loading, and uvicorn startup.
- Root-level `config.example.json` illustrates tool compaction rules; copy it to `config.json` or point `MCP_PROXY_CONFIG_FILE` at a custom path.
- `test_proxy_config.json` is a minimal fixture useful for smoke runs without touching production configs.
- Docker packaging lives at the root (`Dockerfile`, `.dockerignore`). Keep new scripts in subdirectories to avoid polluting the base image context.

## Build, Test, and Development Commands
- Create an environment: ``python3.12 -m venv .venv && source .venv/bin/activate``.
- Install deps: ``pip install -r requirements.txt``.
- Launch locally with env vars (placed in `.env` or the shell):
  ```bash
  MCP_PROXY_CONFIG_FILE=config.json \
  MCP_UPSTREAM_URL=http://localhost:8931/mcp \
  BASE_URL=http://localhost:8000/v1 \
  API_KEY=dev-key \
  MODEL_NAME=openai/gpt-oss-120b \
  python -m mcp_proxy --host localhost --port 8009
  ```
- For container builds: ``docker build -t mcp-compact .`` then run with matching environment variables.

## Coding Style & Naming Conventions
- Follow standard PEP 8 with 4-space indentation, type hints, and `snake_case` function names as seen in `mcp_proxy/server.py:22`.
- Use structured logging (`logging.getLogger`) instead of prints; align log levels with the `--log-level` flag.
- Keep async flows explicit—new coroutines should mirror the `async def` patterns already in `server.py` and `__main__.py`.

## Testing Guidelines
- Automated tests are not yet present; add `pytest` + `pytest-asyncio` cases under a new `tests/` directory when contributing logic.
- Prefer scenario-focused tests that spin up a proxy with `test_proxy_config.json` and exercise representative tool calls via the MCP client stubs.
- For manual checks, run the proxy against a staging upstream and confirm summarization logs before opening a PR.

## Commit & Pull Request Guidelines
- Use imperative, concise commit subjects (e.g., "Add python-dotenv support"), mirroring existing history.
- Each PR should describe the change, list config/env updates, and note manual verification steps (proxy run, docker build, etc.).
- Link relevant issues and include screenshots or captured logs when altering runtime behaviour or configuration.

## Configuration & Secrets
- `.env` is auto-loaded via `python-dotenv`; never commit real credentials. Share sample variables by updating `.env.example` if new settings are introduced.
- Document any new environment variables in the README and ensure defaults keep the proxy bootable without private keys.
