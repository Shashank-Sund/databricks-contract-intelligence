# Contract Intelligence

A config-driven AI assistant you deploy as a **Databricks App** inside your own
workspace. You ask plain questions and it answers using two things at once:

- your **structured data** (tables), through an **AI/BI Genie** space, and
- your **documents** (PDFs), through grounded document search (**Vector Search**
  RAG).

A **supervisor agent** decides which one to use, or both, and combines the
answer. Everything runs on your own Databricks foundation-model endpoints, so the
data never leaves your tenant. The assistant's persona, its tools, and the
routing all come from a **config file**, not the code, so the same app serves any
domain.

> Healthcare example: *"Which payer underpaid us the most versus our contracted
> rates, and what does that contract say about appealing it?"* → the agent pulls
> the dollar figure from the claims tables **and** quotes the appeal clause from
> the right contract, in one answer.

## What it shows off (Databricks features, working together)

| Feature | What it does here |
|---|---|
| **AI/BI Genie** | Natural-language questions over your tables (one space, or several routed by description). |
| **Vector Search** | Grounded Q&A over your documents, with source-file/page citations. |
| **Supervisor agent** | Routes each question to Genie, the document search, or both, then writes the combined answer. |
| **Foundation Models** | A reasoning model (the agent) + an answer model (document RAG), both as Databricks serving endpoints. |
| **`ai_extract` / `ai_parse_document`** | Turn your PDFs into a normalized terms table and searchable text. |
| **Unity Catalog governance** | User-scoped auth (OBO) so each person sees only what their UC permissions allow; optional column masks. |
| **Databricks Apps + Delta** | The React + FastAPI chat app, with per-user chat history, deployed and SSO-secured in your workspace. |

## What you bring vs. what the template provides

| You bring | The template provides |
|---|---|
| Your **tables** in Unity Catalog | The chat app, per-user history, SSO |
| A **Genie space** built on those tables (+ good instructions) | The supervisor agent (routing, multi-tool, multi-space, compound answers) |
| Your **documents** in a Volume | The RAG pipeline + the document-search tool |
| A few **config values** (endpoints, IDs, catalog/schema, auth mode) | The notebooks, the governance recipe, the deploy path |

The Genie space is the one piece only you can build, because it depends on your
data model and your business definitions. The template guides you (see
`notebooks/03_create_genie_space.py`) and then uses the space id(s) you give it.

## How it works (the flow)

```
                       ┌──────────────────────────────┐
   you ask  ─────────► │  Supervisor agent (Claude)    │
                       │  persona + tools from config  │
                       └───────┬───────────────┬───────┘
                  genie tool(s)│               │vector_search tool
                               ▼               ▼
                    ┌────────────────┐  ┌─────────────────────┐
                    │  Genie space   │  │  Vector Search index │
                    │ (governed SQL) │  │  (your documents)    │
                    └───────┬────────┘  └──────────┬──────────┘
                            └───────► combined ◄────┘
                                       answer + citations
```

Tool calls run under the signed-in user's credentials (OBO) by default, so Unity
Catalog permissions and masks apply per user. Chat history is per-user and
persists across reloads.

## Quick links

- **See it work first (~30 min):** stand up the included **Northwind Health**
  sample end-to-end (synthetic data, pre-filled config):
  **[`examples/northwind-health/README.md`](examples/northwind-health/README.md)**.
- **Adapt it to your own data:** the click-by-click guide is
  **[`DEPLOY.md`](DEPLOY.md)**.
- **Just want the document chatbot first?** The shortest route (documents only,
  no Genie) is the "Fast path" section of
  **[`DEPLOY.md`](DEPLOY.md#fast-path-just-the-contract-chatbot-documents-only-no-genie)**.
- **Make it yours (branding, prompts, model, AI Gateway, logging):**
  **[`CUSTOMIZE.md`](CUSTOMIZE.md)**.
- **The notebooks you run:** [`notebooks/`](notebooks/) —
  `01_extract_contract_terms.py`, `02_build_document_search_index.py`,
  `03_create_genie_space.py`.

## Repo structure

```
.                                  ← THE TEMPLATE (generic, no domain specifics)
├── server/                # FastAPI backend: config-driven supervisor agent, Genie + RAG tools, history, auth
├── client/                # React frontend (the chat UI)
├── config/app.json        # the template config you edit (persona, tools, endpoints, IDs, auth_mode)
├── notebooks/             # 01 extract terms · 02 build search index · 03 create Genie space (guide)
├── setup/                 # generic helpers: build a search index, chat_history, governance recipe
├── app.yaml               # Databricks App runtime config (sets APP_CONFIG_PATH, AUTH_MODE, IDs)
├── DEPLOY.md              # adopt-it-to-your-data guide
├── CUSTOMIZE.md           # change branding, prompts, model, AI Gateway, logging
└── examples/
    └── northwind-health/  ← A COMPLETE EXAMPLE INSTANCE (fictional Northwind Health)
        ├── config.json    # filled-in config (catalog northwind / schema contract_intelligence)
        ├── setup.py        # one-click notebook: loads data, regenerates PDFs, builds the index
        ├── data/ contracts/ # pre-built synthetic data + contract PDFs
        ├── *.py *.sql       # the data generators + metric views
        └── README.md        # the click-by-click walkthrough for this example
```

## Costs and safety

- All example data is synthetic; safe to put in any workspace.
- The app runs model calls on your own endpoints (pay-per-token) and a SQL
  warehouse for Genie. Idle cost is near zero; you pay when people use it.
- Nothing leaves your tenant. With AI Gateway turned on (optional), every request
  and response is logged automatically with no code change.

See [`DEPLOY.md`](DEPLOY.md) to get started.
