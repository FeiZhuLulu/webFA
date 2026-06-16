# WebFA Desktop v0.1 Skeleton

WebFA Desktop is a local Agent Action Transaction Gateway. This repository contains the v0.1 project skeleton: Electron desktop shell, Next.js local console, Python FastAPI runtime, SQLite storage initialization, transaction registry loading, and first-pass tests.

This skeleton intentionally does **not** implement real GitHub API calls, real Hugging Face API calls, OAuth, MCP, installer packaging, credential persistence, or real transaction execution.

## Architecture

```text
webfa/
  apps/
    desktop/
      electron/       # Electron shell: window, tray, runtime process manager, IPC
      renderer/       # Next.js console UI
    runtime/          # FastAPI runtime: REST API, startup bootstrap
  packages/
    webfa-core/       # Runtime domain modules: registry, planner, policy, approvals, etc.
    providers/        # Mock/GitHub/Hugging Face provider placeholders
    storage/          # SQLite, SQLAlchemy models, file/credential store placeholders
    schemas/          # Pydantic v2 contracts
  resources/          # YAML transaction/policy/path definitions
  tests/              # Unit, integration, and contract tests
```

Electron is deliberately limited to local shell responsibilities: process management, tray/window, notifications, and IPC. Runtime business logic belongs in Python.

## Local storage paths

The runtime creates the WebFA data directory on startup:

- Windows: `%APPDATA%/WebFA/`
- macOS: `~/Library/Application Support/WebFA/`
- Linux: `~/.config/webfa/`

The directory contains:

```text
config.json
webfa.db
credentials/
proofs/
audits/
artifacts/
logs/
tmp/
```

For tests or isolated development, override it:

```bash
export WEBFA_HOME=/tmp/webfa-dev
```

## Runtime development

Python 3.12 is the target runtime.

```bash
cd webfa
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
python -m uvicorn apps.runtime.main:app --host 127.0.0.1 --port 8787 --reload
```

Health check:

```bash
curl http://127.0.0.1:8787/health
```

Available REST endpoints in this skeleton:

```text
GET /health
GET /v1/providers
GET /v1/transactions
```

## Desktop + Console development

Install Node dependencies:

```bash
cd webfa
npm install
```

Run the full desktop stack:

```bash
npm run dev
```

Run pieces separately:

```bash
npm run dev:renderer   # Next.js console on 127.0.0.1:8788
npm run dev:runtime    # FastAPI runtime on 127.0.0.1:8787
npm run dev:electron   # Electron shell; starts/stops Python runtime
```

The dashboard shows:

- Runtime running/stopped/error
- REST API address
- SQLite DB path
- MCP status placeholder
- GitHub disconnected
- Hugging Face disconnected
- Loaded transaction definitions

## Tests

Python tests:

```bash
pytest
```

Electron type check:

```bash
npm run typecheck:electron
```

Renderer type check:

```bash
npm run typecheck:renderer
```

Full local check after installing both Python and Node dependencies:

```bash
npm run check
```

## v0.1 implemented scope

- Electron window and tray shell
- Electron-managed Python runtime lifecycle
- Runtime crash/error propagation to UI via IPC
- Runtime shutdown on app quit
- FastAPI runtime with `/health`, `/v1/providers`, `/v1/transactions`
- Cross-platform WebFA data directory bootstrap
- SQLite initialization using SQLAlchemy 2.x
- Minimal tables: `provider_connections`, `transactions`, `workspaces`, `plans`, `approvals`, `executions`, `execution_steps`, `proofs`, `audit_events`
- YAML transaction registry loading for:
  - `github.patch_and_open_pr`
  - `hf.compare_and_publish`
- Console dashboard with disconnected provider placeholders
- Tests for health, storage initialization, registry loading, and Electron/runtime contract markers

## Deliberately excluded

- Real GitHub API
- Real Hugging Face API
- Real MCP server
- Real transaction execution
- OAuth
- Installer packaging
- Token storage
- Business logic in Electron main process
