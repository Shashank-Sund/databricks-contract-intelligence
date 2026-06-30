# Deploy guide — click-by-click

This guide assumes **no Databricks experience**. It explains every step and why
it exists. Most of it is clicking buttons in your browser and running three
notebooks.

> **Want to see it work first?** Stand up the included **Northwind Health** sample
> end-to-end (pre-filled, ~30 min): **[`examples/northwind-health/README.md`](examples/northwind-health/README.md)**.
> Then come back here to point the app at *your* data.

---

## The mental model

The app is a chat assistant with a **supervisor agent** that routes each question
to one or more **tools**. Two tool backends ship with it:

- **`genie`** — answers questions about your **structured tables** by calling a
  **Genie space** (governed natural-language SQL). You can configure one space, or
  several (the agent picks by their descriptions).
- **`vector_search`** — answers questions about your **documents** by searching a
  **Vector Search index** (grounded retrieval with citations).

Everything the agent says about *your domain* (its persona, the tool names, the
routing) lives in **one config file** — never in code.

A few words you'll see (plain English):
- **Catalog / schema** = Databricks' "database / folder for tables."
- **Volume** = a Unity Catalog folder that holds files (your PDFs).
- **Warehouse** = the engine that runs SQL. You'll pick a "serverless" one.
- **Serving endpoint** = a hosted AI model you can call.
- **Genie space** = a chat window that answers questions about specific tables.
- **App** = the web app you're deploying (this project).

---

## Prerequisites + permissions

- A **Databricks workspace** you can log into, with **Unity Catalog** enabled
  (it is on almost every workspace today).
- Permission to create catalogs, Volumes, Genie spaces, and Apps. If you're not an
  admin, send your admin this guide — the grant-y parts are flagged.
- **Vector Search** available in your region, and the built-in embedding endpoint
  `databricks-gte-large-en`.
- One or two **chat serving endpoints** (e.g. Claude Sonnet for the agent, Claude
  Opus for document answers). Any OpenAI-style chat endpoint works.

---

## (Optional) Try the Northwind sample first

Follow **[`examples/northwind-health/README.md`](examples/northwind-health/README.md)**:
run its `setup.py` notebook (loads synthetic data, regenerates the contract PDFs,
builds the search index), create a Genie space, fill two ids, deploy. It's the
fastest way to understand the moving parts before using your own data.

---

## The stages, in order (for your own data)

### Stage 1 — Get your data into Unity Catalog
Land your **tables** (the structured side) and your **documents** (PDFs/text, in a
UC **Volume**). If you don't have data yet, study the Northwind example's loader.

### Stage 2 — Run `notebooks/01_extract_contract_terms.py`  *(provided notebook)*
This reads your PDFs from the Volume and uses `ai_parse_document` + `ai_extract` to
pull the specific facts you care about into a Delta table (default `contract_terms`).
**Edit the `CONTRACT_TERMS` dict** in the notebook to list the fields you want
(it's clearly marked). This table is meant to sit in your Genie space **next to**
your claims/transaction tables, so the agent can join "what we were paid" to "what
the contract says."

### Stage 3 — Run `notebooks/02_build_document_search_index.py`  *(provided notebook)*
This turns the same Volume of documents into page-level chunks and a **Vector
Search index** (the document-search tool's data source). It prints the index name;
put it in your config under `rag.vector_search_index`.

### Stage 4 — Create your Genie space(s) and register them  *(you, guided by `notebooks/03_create_genie_space.py`)*
In Databricks: **Genie → New**, pick a serverless SQL warehouse, add your tables
(including the `contract_terms` table from Stage 2), and — this is the important
part — **write good instructions** (define metrics precisely, state join keys,
point to preferred views). Bad instructions are the #1 cause of wrong answers; the
notebook gives a template. Then:

- **Grant access** so the app can run the space (see "User-scoping" below).
- **Copy the space id** from the URL (`/genie/rooms/<id>`) and register it:
  - **Single space:** set `genie.space_id` (or the `GENIE_SPACE_ID` env var).
  - **Multiple spaces:** give each `genie` tool in `agent.tools[]` its own
    `"space_id"` plus a `description` of what it covers; the agent routes by
    description.

> **When added correctly, every accessible space also appears in the app's
> bottom-left "Genie spaces" panel** (that panel lists all spaces the signed-in
> user can access, independent of which spaces the agent routes to).

### Stage 5 — Fill in `config/app.json`
Open it and set:
- `agent.system_prompt` — who the assistant is, in your domain's words.
- `agent.tools[]` — name + description per tool. `backend: "genie"` (optionally
  with `space_id`); `backend: "vector_search"` (optionally with a `scope_filter`).
- `supervisor.endpoint` / `rag.generation_endpoint` — your chat model endpoints.
- `rag.vector_search_index` — from Stage 3.
- `genie.space_id` — your default space (Stage 4).
- `warehouse_id`, `uc.catalog`, `uc.schema`.
- `auth_mode` — `obo` (default) or `service_principal` (see below).

Then update **`app.yaml`** `env:` to match (`DATABRICKS_HOST`, `APP_CONFIG_PATH`,
`CATALOG`, `SCHEMA`, `WAREHOUSE_ID`, `GENIE_SPACE_ID`, `AUTH_MODE`).

### Stage 6 — Deploy the Databricks App
Sidebar → **Compute** → **Apps** → **Create app**. Point it at this Git folder.
Databricks creates a hidden **service principal** (a robot user) the app runs as.

Add the app's **resources** so its service principal can use everything:

| Resource type | Pick | Permission |
|---|---|---|
| Serving endpoint | your reasoning (agent) endpoint | CAN QUERY |
| Serving endpoint | your answer (RAG) endpoint | CAN QUERY |
| Serving endpoint | `databricks-gte-large-en` | CAN QUERY |
| SQL warehouse | your warehouse | CAN USE |
| Genie space | each space you configured | CAN RUN |

Also set the app's **user_api_scopes** so OBO tokens carry the right scopes:
`sql`, `dashboards.genie`.

> ⚠️ If you later edit the app via CLI/API, always include **all** resources in
> the call — a partial update wipes the ones you omit.

**Grant the app's service principal Unity Catalog access.** The resources above
cover the model/warehouse/Genie endpoints, but the app also needs UC grants on
your data and its history table. Find the service principal id on the app's page,
then (as a catalog owner/admin) run:

```sql
-- replace <sp> with the app's service principal id, and your catalog/schema
GRANT USE CATALOG ON CATALOG <catalog>                       TO `<sp>`;
GRANT USE SCHEMA  ON SCHEMA  <catalog>.<schema>              TO `<sp>`;
GRANT SELECT      ON SCHEMA  <catalog>.<schema>              TO `<sp>`;  -- data (SP fallback path)
GRANT MODIFY      ON TABLE   <catalog>.<schema>.chat_history TO `<sp>`;  -- so chat history persists
```

`MODIFY` on `chat_history` is what makes conversation history save. **Without it,
turns are written nowhere and the history list is empty after you reload the app.**

Click **Deploy**, wait for **Running**, open the app URL. You sign in with SSO.

### Stage 7 — Test
Ask a structured question, a document question, and a compound one. Confirm the
agent routes correctly and combines results. Reload to confirm history persists.

---

## User-scoping: OBO vs. service_principal

Set with `auth_mode` in config or the `AUTH_MODE` env var in `app.yaml`.

- **`obo` (default, on-behalf-of-user):** Genie runs **as the signed-in user**, so
  Unity Catalog permissions and column masks apply *per user*. This is the right
  choice when different people should see different data.
  - **Requires:** each user must have UC grants on the underlying tables **and**
    `CAN RUN` on the Genie space. The app's service principal still needs `CAN RUN`
    (for the spaces-list panel and the fallback path).
  - The app sets `user_api_scopes` (`sql`, `dashboards.genie`) so the forwarded
    user token can call Genie/SQL.
- **`service_principal`:** the app **always** uses its own service-principal token.
  Simpler (no per-user UC grants), but **every user sees the same SP-scoped view**.
  Use this for a shared, single-view demo or when per-user governance isn't needed.

**Best practices**
- Start with `service_principal` to prove the app works end-to-end, then switch to
  `obo` once per-user grants are in place.
- Keep masks/permissions in **Unity Catalog**, not the app — they're then enforced
  everywhere (Genie, SQL editor, dashboards, and this app).
- New **account** groups (used by masks) take a few minutes to propagate before
  `is_account_group_member()` returns true. Set them up before you demo.

---

## (Optional) Governance / column masking
Apply Unity Catalog column masks so different groups see different data. The recipe
in `setup/governance_masking.sql` is parameterized — give it your group names and
the columns to mask. Because the mask lives in Unity Catalog, it's enforced through
Genie *and* the agent.

---

## Reference: the config file
See `config/app.json` (the documented template) and
`examples/northwind-health/config.json` (a complete, working instance). To change
branding/identity, the system prompts, the model, AI Gateway, or logging, see
**[`CUSTOMIZE.md`](CUSTOMIZE.md)**.

## Troubleshooting
| Symptom | Fix |
|---|---|
| "App Not Available" after deploy | Wait 1–2 min; the app binds to the injected port automatically. |
| 403 mentioning "model-serving"/"scope" | The app's **resources** are missing or were wiped — re-add them (Stage 6). |
| Genie panel empty / agent can't query data | The service principal (and, under OBO, each user) needs **CAN RUN** on the Genie space; check `user_api_scopes` includes `dashboards.genie`. |
| "No relevant document text found" | The Vector Search index is still building, or `rag.vector_search_index` is wrong. |
| Agent uses generic tool names / ignores your prompt | `APP_CONFIG_PATH` isn't resolving — confirm it points at your config (relative paths resolve from the repo root). |
| Each user sees the same data under OBO | They lack per-user UC grants or `CAN RUN` on the space; or `AUTH_MODE` is `service_principal`. |
| Chat history is empty after you exit and reopen | The app's service principal lacks **MODIFY** on the `chat_history` table — grant it (Stage 6). |
