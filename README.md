# Serena Memory

Serena Memory is a fork of the Nocturne Memory MCP server, adapted for a private long-term assistant with semantic recall, remote summary memory, and token-bounded recall packages.

The current goal is simple: keep durable personal memory available to agents without constantly injecting a large prompt into every conversation.

## Current Capabilities

- MCP memory tools for reading, writing, updating, deleting, aliasing, triggers, and lexical search
- Semantic active-memory search using Qwen-compatible embeddings
- `recall_memory` for token-bounded semantic + lexical + remote-summary recall
- Remote summary memory with source provenance
- Manual consolidation workflow:
  - `plan_consolidation`
  - `supersede_remote_summary`
  - `create_remote_summary`
  - `inspect_remote_summary_batch`
  - `recall_memory`
- Namespace isolation for separate agents or game/session memory spaces
- SQLite-first local deployment

## Cache Protection

`recall_memory` defaults to a 2000-token budget:

```text
semantic_limit = 5
lexical_limit = 5
token_budget = 2000
```

The recall formatter builds the final package and verifies that the estimated output stays within budget. If the result would exceed the budget, it reduces the number of returned items.

This protects the main conversation cache from being flooded by memory recall.

Boot memory is separate: `read_memory("system://boot")` reads configured boot URIs. Keep boot memories short and stable.

## Namespace Strategy

Use namespaces to isolate memory spaces:

- default namespace: Serena's core/persona/user memory
- `rimworld`: RimWorld game/session memory
- additional namespaces: other agents, tests, or role-specific contexts

In stdio mode, set:

```powershell
$env:NAMESPACE = "rimworld"
```

In HTTP/SSE mode, use:

```text
?namespace=rimworld
X-Namespace: rimworld
```

## Setup

Install backend dependencies in a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Build the frontend:

```powershell
cd frontend
npm install
npm run build
```

Run tests:

```powershell
cd ..
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

Run the MCP server:

```powershell
.\.venv\Scripts\python.exe backend\mcp_server.py
```

Run SSE/HTTP mode:

```powershell
.\.venv\Scripts\python.exe backend\run_sse.py
```

## MCP Client Example

```json
{
  "mcpServers": {
    "serena-memory": {
      "command": "C:/Users/pc/Desktop/workplace/Serena_memory/.venv/Scripts/python.exe",
      "args": ["C:/Users/pc/Desktop/workplace/Serena_memory/backend/mcp_server.py"],
      "env": {
        "NAMESPACE": ""
      }
    },
    "serena-memory-rimworld": {
      "command": "C:/Users/pc/Desktop/workplace/Serena_memory/.venv/Scripts/python.exe",
      "args": ["C:/Users/pc/Desktop/workplace/Serena_memory/backend/mcp_server.py"],
      "env": {
        "NAMESPACE": "rimworld"
      }
    }
  }
}
```

## SiliconFlow

For Qwen embeddings, set the API key outside the repo:

```powershell
$env:SILICONFLOW_API_KEY = "..."
```

Do not commit API keys or local `.env` files.

## Project Status

This repository is currently in active adaptation for a private assistant. The memory MCP layer is usable; persona prompt, boot memory content, and game integration policy are still being finalized.
