# Customize the app for your organization

Everything domain-specific lives in **one config file** (no code changes). The
included **Northwind Health** example is just a sample; this guide shows exactly
what to change to make the app yours, and where.

## The one rule: config, not code

`app.yaml`'s `APP_CONFIG_PATH` decides which config the app loads. The Northwind
sample points it at `examples/northwind-health/config.json`. For your own
deployment, the clean path is:

1. Edit **`config/app.json`** (the documented template) with your settings.
2. Set `APP_CONFIG_PATH: "config/app.json"` in `app.yaml`.

(Or copy the template to `examples/<your-org>/config.json` and point at that.)

**All changes below take effect on the next deploy** (re-sync the repo, then
`databricks apps deploy <app>`). The UI and the agent both read the config fresh
on deploy.

---

## 1. Identity / branding — "the chatbot thinks it's Northwind"

The assistant's identity comes from **two** places. You must change **both**, or
the UI will say your org while the model still says Northwind.

**(a) The web UI** (header, home screen) — served to the browser via `/api/config`:

| Field (in config) | Controls |
|---|---|
| `branding.name` | The app name shown in the UI |
| `branding.tagline` | One-line tagline |
| `branding.subtitle` | Smaller subtitle (the example uses it for "Northwind Health (synthetic demo)") |
| `home.title` | Home-screen heading |
| `home.description` | Home-screen blurb |
| `home.suggestions` | The starter-prompt buttons |

**(b) The model's self-identity** — this is *why the chatbot says "Northwind."*
The org name is written into the prompts:

| Field (in config) | What to change |
|---|---|
| `agent.system_prompt` | Says "...for **Northwind Health**'s managed care and revenue-cycle team." Replace the org name (and reword the domain if needed). |
| `rag.system_prompt` | Says "You are a payer-contract analyst for **Northwind Health**." Replace the org name. |

Search the config for `Northwind` and replace every occurrence with your org.

---

## 2. System prompts and tool descriptions — where and what

All of these are keys in the config file:

- **`agent.system_prompt`** — the **supervisor's** master persona + routing rules
  (when to use the data tool vs. the document tool vs. both). This is the single
  most important prompt. Edit it to your domain, org, and rules.
- **`agent.tools[].description`** and **`agent.tools[].question_description`** —
  what each tool is for. **The model routes on these descriptions.** If the agent
  sends questions to the wrong tool, sharpen the wording here.
- **`rag.system_prompt`** — how the **document-answer** model writes (tone,
  "use only the excerpts," and the **citation format**, e.g.
  `"(file.pdf, page 2)"`). If left `""`, a sensible built-in default is used
  (`server/services/contract_search.py` `DEFAULT_DOC_SYSTEM`); set this field to
  control the voice and citation style.

---

## 3. Change the model

Point these at any chat (OpenAI-style) serving endpoint **name** in your
workspace, then add that endpoint as a `CAN QUERY` **resource** on the app
(see `DEPLOY.md` Stage 6) so the app's service principal can call it.

| Field (in config) | Model used for |
|---|---|
| `supervisor.endpoint` | The agent "brain" (tool-calling loop). Also `supervisor.max_tokens`, `supervisor.max_tool_iterations`. |
| `rag.generation_endpoint` | Writing the grounded document answer. |

You can use Databricks Foundation Model endpoints (`databricks-claude-opus-4-8`,
`databricks-claude-sonnet-4-6`, ...), a **provisioned-throughput** endpoint, or an
**External Model** endpoint (OpenAI/Azure/Bedrock) — the app only needs the name.

**Embedding model** (used for document *search*) is set when you build the index,
not here: the `embedding_model` widget in
`notebooks/02_build_document_search_index.py` (default `databricks-gte-large-en`).
Changing it means **rebuilding the index**, then updating
`rag.vector_search_index`. That endpoint also needs `CAN QUERY` on the app.

---

## 4. Enable AI Gateway (usage tracking, payload logging, rate limits, guardrails)

**AI Gateway is configured on the serving endpoints the app calls, not in this
repo.** The app just calls endpoints by name, so if you point
`supervisor.endpoint` / `rag.generation_endpoint` at a **gateway-enabled
endpoint**, you get the governance with no app change.

To enable: **Workspace → Serving → open the endpoint → AI Gateway** tab, then turn
on what you want:

- **Usage tracking** — per-request token/cost attribution.
- **Inference tables (payload logging)** — logs every request + response to a
  Delta table (you pick catalog/schema). This is your audit log of what the model
  was asked and what it answered.
- **Rate limits** — per-user / per-endpoint request or token caps.
- **Guardrails** — PII detection/masking, safety, topic filtering.
- **Fallbacks / traffic split** — route to a backup model on error or A/B models.

For a non-Databricks model, create an **External Model** serving endpoint (it has
AI Gateway built in) and use its name as your endpoint. Built-in
`databricks-claude-*` endpoints support AI Gateway too.

---

## 5. Logging and observability — three layers

1. **App logs (stdout).** The FastAPI app logs at `INFO`
   (`server/app.py` `logging.basicConfig`). View them in **Compute → Apps → your
   app → Logs**, or `databricks apps logs <app>`. For more detail, change the
   level in `server/app.py` to `logging.DEBUG` and redeploy.
2. **LLM request/response logs.** Turn on **AI Gateway inference tables**
   (Section 4) to get a queryable Delta table of every model call.
3. **Conversation history.** The app already writes **every Q&A turn** to the
   `chat_history` Delta table (`uc.catalog`.`uc.schema`.`uc.history_table`). Query
   it for usage and analytics. Genie's own SQL executions also appear in the SQL
   warehouse's **Query History**.

---

## 6. Other knobs (quick reference)

| Field (in config) / setting | Does |
|---|---|
| `genie.space_id` | The default Genie space. |
| per-tool `space_id` on a `genie` tool | Route across **multiple** Genie spaces (see `notebooks/03_create_genie_space.py`). |
| `auth_mode` (`obo` / `service_principal`) | User-scoped vs. shared identity (see `DEPLOY.md`). |
| `history.backend` (`delta` / `lakebase`) | Where chat history is stored. |
| `rag.num_results`, `rag.columns` | How many chunks to retrieve and which index columns feed the answer. |
| `agent.tools[].scope_filter` | Keep a document question about one entity from being answered with another's similar text. |
| `upload.max_pages`, `upload.max_mb` | Ad-hoc document upload limits. |

---

## 7. Apply your changes

1. Edit the config (and `app.yaml` `env:` if you changed `CATALOG`, `SCHEMA`,
   `GENIE_SPACE_ID`, `WAREHOUSE_ID`, or `AUTH_MODE`).
2. Re-sync the repo to your workspace.
3. `databricks apps deploy <your-app>`.
4. Reload the app. The new branding, prompts, and models are live.
