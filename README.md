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

Cache protection is a baseline requirement:

- Keep boot memory short, stable, and cache-friendly.
- Treat `recall_memory(token_budget=2000)` as the default recall path for topic-specific context.
- Do not put long biographies, full chat history, game logs, or large summaries directly into boot memory.
- Store long-lived detail in ordinary memories or remote summaries, then recall it semantically when needed.
- A good boot target is roughly 1200-1800 tokens total across all boot URIs.

In practice:

- `system://boot` = identity anchor and operating rules.
- `recall_memory` = topic-specific memory package.
- `plan_consolidation` / `create_remote_summary` = long-term compression workflow.

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

Recommended namespace layout:

- default namespace: Serena's normal persona, user, relationship, and assistant memory
- `rimworld`: RimWorld game memory
- future game namespaces: one namespace per game or campaign

Do not mix game session facts into Serena's default persona memory unless they should permanently affect the assistant outside the game.

## Runtime Deployment Strategy

Recommended first deployment: run Serena Memory locally on Windows.

Do not use the 1GB RAM / 10GB storage VPS as the primary memory host yet. The VPS is already running network proxy and `tt-sync`, and the memory database is private, high-value state. Keep the main SQLite database local until remote access is genuinely required.

Preferred local service command:

```powershell
cd C:\Users\pc\Desktop\workplace\Serena_memory
.\.venv\Scripts\python.exe backend\run_sse.py
```

Default local service:

```text
http://127.0.0.1:8233
```

Use the VPS later only as a reverse proxy or tunnel endpoint if needed. Do not expose Serena Memory publicly without an API token and transport security review.

## Persona And Boot Memory

Persona should be split into two layers:

1. Client system prompt: short operating protocol.
2. Serena Memory boot nodes: durable identity and relationship state.

The client prompt should say only the minimum needed:

- read `system://boot` at session start
- use `recall_memory` for topic-specific recall
- write important durable facts back into memory
- keep boot memory small

Recommended default boot nodes:

```text
core://agent
core://my_user
core://agent/my_user
```

Useful additional non-boot nodes:

```text
core://agent/memory_policy
core://agent/interaction_style
core://agent/tool_policy
```

For RimWorld, use the `rimworld` namespace and game-domain nodes such as:

```text
game://rimworld/colony
game://rimworld/story_so_far
game://rimworld/current_goals
game://rimworld/rules
game://rimworld/npcs
```

Game nodes can be consolidated into remote summaries over time, but near memories should not be deleted or archived automatically.

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
