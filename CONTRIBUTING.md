# Contributing

Short guide for people forking Contract Intelligence or working on it locally.

## Dev setup

Prereqs: Python 3.11+, `uv`, Node.js + npm, the Databricks CLI authenticated
against the workspace you want to deploy into, and a `.env.local` filled in from
`.env.template`.

```bash
git clone <your-fork-url> databricks-contract-intelligence
cd databricks-contract-intelligence
cp .env.template .env.local
# fill in DATABRICKS_HOST and DATABRICKS_TOKEN (a PAT) for local dev

# run the backend (8000) and frontend (3000) in dev mode
./scripts/start_dev.sh
```

`start_dev.sh` installs deps on first run. The Vite dev server proxies `/api`
calls to FastAPI, so use http://localhost:3000 in the browser.

For deploying to a workspace, follow [`DEPLOY.md`](DEPLOY.md).

## Code style

Python is formatted and linted with `ruff`. TypeScript is formatted with
`prettier` and type-checked with `tsc`.

```bash
./scripts/fix.sh      # ruff format + ruff --fix + prettier
./scripts/check.sh    # ruff check + tsc --noEmit
```

Project conventions worth knowing:

- 2-space indentation in Python. (Yes, really; matches the existing tree.)
- Single-line docstrings are fine on obvious functions. Don't pad with
  Args/Returns blocks unless the function is genuinely complex.
- No em dashes. No emojis in code, docstrings, or comments.
- `from __future__ import annotations` at the top of every Python module.
- Keyword-only args for any service function that takes more than two
  parameters; we use `*, host, token, ...` everywhere.

## How it's wired

```
server/            FastAPI backend
  app.py           Entry point; wires up routers under /api, serves client/out
  routers/         HTTP endpoints (chat, config, export, upload, health)
  services/        Business logic:
    model_client.py    multi-model streaming + completion against serving endpoints
    model_access.py    optional per-user, per-model group filtering (fail-open)
    history_store.py   per-user chat history in a Delta table
    export_service.py  Word / PDF / Markdown builders
    doc_parse.py       PDF parsing via ai_parse_document
    credentials.py     SP OAuth (prod) / PAT (dev) resolution
    rbac_simple.py     user identity from the Apps SSO header
  config_loader.py   loads config/app.json
client/            Vite + React frontend; built into client/out for prod
config/            app.json (branding, models, personas, uc, upload limits)
scripts/           setup.py (UC provisioning + grants), start_dev.sh, fix.sh, check.sh
```

## How to add a model or persona

No code changes needed, both are config. Add an entry to the `models` or
`personas` array in `config/app.json` and redeploy. See the "Customizing the app"
section of [`DEPLOY.md`](DEPLOY.md) for the exact fields and examples (including
restricting a model to workspace groups via `allowed_groups`).

## How the request flow works

1. `POST /api/chat` (`server/routers/chat.py`) resolves the chosen model's serving
   endpoint and the persona's system prompt from config, then streams the reply
   over SSE.
2. The active model + persona label is injected into the system prompt so a
   mid-conversation switch is observable.
3. Optional per-model `allowed_groups` is enforced here (403 if the user isn't in
   an allowed group; fails open if the user's groups can't be read).
4. Both the user message and assistant reply are persisted to the `chat_history`
   Delta table, scoped to the signed-in user's email.

`GET /api/config/app` returns a UI-safe view (labels + ids only, no internal
endpoint names or persona system prompts), with the model list already filtered
to what the current user may use.

## How to test changes locally

There is no automated test suite yet. The supported manual loop:

1. Run `./scripts/start_dev.sh`.
2. Open http://localhost:3000, send a chat, switch models/personas, upload a PDF,
   and export a reply to Word/PDF/Markdown.
3. Inspect the history table in your workspace to confirm rows were written:
   ```sql
   SELECT * FROM <catalog>.<schema>.chat_history ORDER BY created_at DESC LIMIT 10;
   ```
4. Run `./scripts/check.sh` before opening a PR.
