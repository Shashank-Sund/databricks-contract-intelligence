# Example: Healthcare Revenue-Cycle (Northwind Health)

A complete, ready-to-run instance of the template: synthetic payer contracts +
claims for a fictional **Northwind Health**. The config in this folder
(`config.json`) is already filled in, so you can stand the whole thing up and
see it work before adapting the template to your own data.

> To deploy the app against this example, set `APP_CONFIG_PATH` to
> `examples/northwind-health/config.json` (the included `app.yaml` already does).

---

# Deploy Contract Intelligence — step by step

This guide assumes you have **never used Databricks**. Follow it top to bottom.
Most of it is clicking buttons in your web browser. Total time: ~30–45 minutes,
most of which is waiting for one notebook to run.

There are **3 required phases** and **1 optional** one:

1. **Build the data** — run one notebook (click *Run all*).
2. **Create the Genie space** — a few clicks; it's the "brain" that reads the claims tables.
3. **Create and deploy the app** — point it at this project; paste two IDs.
4. *(Optional)* **Governance demo** — turn on PHI masking for two user groups.

---

## Before you start

You need:

- A **Databricks workspace** you can log into (a web address like
  `https://something.cloud.databricks.com` or `...azuredatabricks.net`). If you
  don't have one, ask your admin, or start a free trial at databricks.com.
- Permission to create things (catalogs, apps). If you're not an admin, send your
  admin this guide; the grant-y parts are flagged.

A few words you'll see (plain-English):
- **Catalog / schema** = Databricks' version of "database / folder for tables."
- **Warehouse** = the engine that runs SQL queries. You'll pick a "serverless" one.
- **Serving endpoint** = a hosted AI model you can call (here, Claude).
- **Genie space** = a chat window that answers questions about specific tables.
- **App** = the web app you're deploying (this project).

---

## Phase 1 — Build the data (run one notebook)

**1.1 Add this project to your workspace.**
In the left sidebar click **Workspace** → your home folder → the **⋮** (or
"Create") menu → **Git folder** (sometimes called "Repo"). Paste this project's
GitHub URL, then **Create Git folder**. You now have the whole project inside
Databricks.

**1.2 Open the setup notebook.**
In the Git folder, open **`examples/northwind-health`** → **`setup`**. At the top right, attach it to
**Serverless** (or any running compute) using the **Connect** button.

**1.3 Run it.**
Leave the boxes at the top at their defaults (catalog `northwind`, schema
`contract_intelligence`). Click **Run all** at the top.

What happens (you can watch the cells turn green):
- Creates the catalog, schema, and a volume for the PDFs.
- Loads the 3 demo tables (`claims`, `contract_terms`, `contract_chunks`).
- Creates the reporting views and the `chat_history` table.
- Uploads the contract PDFs.
- Builds the **Vector Search index** — *this one takes a few minutes the first
  time. That's normal.* Let it finish.
- (Optional) sets up PHI masking.

**1.4 Copy two things the last steps print:**
- the **Vector Search index name** (e.g. `northwind.contract_intelligence.contract_chunks_index`)
- the **Vector Search endpoint name** (e.g. `contract_intelligence_vs`)

When the final two cells show a denial-rate table and an underpayment table, the
data layer is done. ✅

---

## Phase 2 — Create the Genie space

This is the component that answers number questions ("which payer underpaid us…").

**2.1** In the left sidebar click **Genie** → **New** (or "+ New space").

**2.2 Pick a warehouse.** Choose any **Serverless** SQL warehouse. (If there isn't
one, click **SQL Warehouses** in the sidebar → **Create** → accept defaults →
**Create**, then come back.)

**2.3 Add the tables.** Click **Add tables / data** and select, from
`northwind` → `contract_intelligence`:
- `claims`
- `contract_terms`
- `denial_rate_by_payer`
- `reimbursement_variance`
- `underpayment_dollars_by_payer_drg`
- `claims_contract_enriched`
- `revenue_cycle_metrics`
- `renewal_risk`

**2.4 Name it** `Contract Intelligence`.

**2.5 Paste these Instructions** (find the "Instructions" box in the space
settings and paste this in — it makes the answers accurate):

```
This space answers payer-contract and revenue-cycle questions for Northwind
Health System using the claims and contract_terms tables and the reporting views.

Definitions:
- "Underpayment" / "revenue leakage" / "shortfall" = the contracted amount minus
  what we collected, where collected = paid_amount + patient_responsibility.
  Use the reimbursement_variance or underpayment_dollars_by_payer_drg views.
  NEVER compute paid_amount alone versus contracted (patient responsibility is
  not underpayment). Exclude denied claims from underpayment math.
- "Denial rate" = denied claims / total claims, by payer. CARC 29 = timely-filing
  denial; CARC 197 = no-prior-authorization denial.
- Inpatient claims join contract_terms on (payer_name, drg_code); outpatient on
  (payer_name, cpt_code).
- For renewal questions ("which contracts renew soon", "renewal risk"), use the
  renewal_risk view. It already computes days_to_renewal against the current date
  and a renewal_window band, alongside each payer's total underpayment and denial
  rate. Do NOT guess today's date or reason from raw term dates.

Prefer the reporting views over raw aggregation when one fits the question.
```

> **Why `renewal_risk` matters:** without it, the agent tries to reason about
> "today" from raw `term_date` values and can guess the date wrong. The view does
> the date math in SQL, so renewal answers stay correct.

**2.6 Save**, then ask a test question like *"What is our denial rate by payer?"*
You should get Humana highest at ~19%.

**2.7 Copy the space ID.** Look at the page's web address. It contains
`/genie/rooms/<long-id>`. Copy that long id — you'll paste it in Phase 3.

---

## Phase 3 — Configure and deploy the app

**3.1 Find your model endpoints.** In the sidebar click **Serving**. You'll see a
list of AI models. This app expects three:
- a **Claude Sonnet** endpoint (the agent's reasoning) — e.g. `databricks-claude-sonnet-4-6`
- a **Claude Opus** endpoint (document answers) — e.g. `databricks-claude-opus-4-8`
- an **embeddings** endpoint — `databricks-gte-large-en` (built in)

If you don't have Claude endpoints, use whatever chat models your workspace lists
(any OpenAI-style chat endpoint works) and note their exact names. If you can't
find Claude, ask your admin to enable the Foundation Model "Claude" endpoints, or
pick another listed chat model.

**3.2 Edit `config/app.json`** (open it in the Git folder, or edit locally). Set:
- `supervisor.endpoint` → your Sonnet (or chosen chat) endpoint name
- `rag.generation_endpoint` → your Opus (or chosen chat) endpoint name
- `rag.vector_search_index` → the index name from **Phase 1.4**
- `genie.space_id` → the space ID from **Phase 2.7**
- `warehouse_id` → your warehouse's id (open **SQL Warehouses** → click your
  warehouse → the id is in the page URL and the "Connection details")
- `uc.catalog` = `northwind`, `uc.schema` = `contract_intelligence` (leave as-is if
  you used the defaults)

**3.3 Edit `app.yaml`** (same folder). Update the `env:` values to match:
`DATABRICKS_HOST` (your workspace URL), `CATALOG`, `SCHEMA`, `WAREHOUSE_ID`,
`GENIE_SPACE_ID`. (These mirror what you just set in `config/app.json`.)

**3.4 Create the app.** Sidebar → **Compute** → **Apps** → **Create app**. Give it
a name (e.g. `contract-intelligence`). Choose **deploy from workspace files** and
point it at this Git folder. Databricks creates a hidden "service principal" (a
robot user) that the app runs as — remember this, it matters next.

**3.5 Give the app permission to use the models, warehouse, and Genie.**
In the app's **Edit / Configure** screen, add these **resources**:

| Resource type | Pick | Permission |
|---|---|---|
| Serving endpoint | your Sonnet endpoint | CAN QUERY |
| Serving endpoint | your Opus endpoint | CAN QUERY |
| Serving endpoint | `databricks-gte-large-en` | CAN QUERY |
| SQL warehouse | your warehouse | CAN USE |
| Genie space | the one from Phase 2 | CAN RUN |

> ⚠️ **Important:** if you ever change the app's settings later through the
> command line or API, you must include **all** of these resources each time, or
> they get wiped and the app loses access. (Easiest to manage them in this UI.)

**3.6 Deploy.** Click **Deploy**. Wait for it to show **Running**, then click the
app's URL.

**3.7 Sign in and test.** You'll log in with SSO automatically. Ask:
*"Which payer and DRG had the largest underpayment versus contracted rates, and
what does that contract say about appealing it?"* — you should get UnitedHealthcare
/ DRG 470 / ~$127,800 plus the appeal clause. 🎉

---

## Phase 4 — (Optional) Governance / PHI-masking demo

This shows Unity Catalog hiding patient identifiers from a "Research Analyst"
group while a "BI Analyst" group sees everything. The masks were already created
in Phase 1; this turns them into a live before/after.

> Needs **account admin** access (the account console, not just the workspace).

**4.1 Create two groups.** Account console → **User management** → **Groups** →
**Add group**: create `northwind_bi_analysts` and `northwind_research_analysts`.

**4.2 Add members.**
- Add **yourself** to `northwind_bi_analysts` (so you see full data).
- Add the **app's service principal** (the robot user from Phase 3.4, name starts
  with `app-`) to `northwind_bi_analysts` too, so the app shows full data.
- Add a teammate (or a second test login) to `northwind_research_analysts` for the
  masked view.

**4.3 Show it.** In the **Genie space** or a **SQL editor**, run:
`SELECT claim_id, member_id, patient_id FROM northwind.contract_intelligence.claims LIMIT 5;`
- A **BI analyst** sees real IDs.
- A **Research analyst** sees `REDACTED`.

> Note: changing someone's group membership takes **a few minutes** to take
> effect (Databricks propagation). Set it up before you demo, not live.

**About per-user masking inside the app:** by default the app runs as its service
principal, so it shows that identity's view (full data, since you added the SP to
BI). Showing *each logged-in user's* own masked view in the app requires
"on-behalf-of-user" (OBO) authorization, which is finicky to enable; the
reliable place to show the per-group difference is the Genie UI / SQL editor
above.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| **"App Not Available"** right after deploy | Give it 1–2 minutes to start. The app binds to the port Databricks provides automatically. |
| **403 error mentioning "model-serving" or "scope"** | The app's **resources** are missing or got wiped — re-add them (Phase 3.5). |
| **Genie panel is empty in the app** | The app's service principal needs **CAN RUN** on the Genie space — add it as a resource (Phase 3.5) or share the space with it. |
| **"could not find the clause" on a contract question** | The Vector Search index is still building (Phase 1) — wait a few minutes and retry. |
| **No Claude endpoints in Serving** | Use any chat endpoint your workspace has; set its name in `config/app.json` (`supervisor.endpoint`, `rag.generation_endpoint`). Ask your admin to enable Foundation Model Claude endpoints if you want Claude specifically. |
| **Chat history doesn't persist** | Make sure Phase 1 finished (it creates the `chat_history` table). |

---

## What's optional vs required

- **Required:** Phases 1–3. That's a fully working app.
- **Optional:** Phase 4 (governance demo), AI Gateway (turn it on in **Serving →
  your endpoint → AI Gateway** to log every request/response — no code change),
  and Lakebase instead of Delta for chat history (set `history.backend` in
  `config/app.json`).

---

## Companion AI/BI Dashboard (show it next to the app)

The same metric views power a Databricks **AI/BI Dashboard** — a visual,
self-serve BI view to show alongside the conversational app. Create it from the
views (all are in `northwind.contract_intelligence`):

| Tile | View |
|---|---|
| Total claims / total underpayment / overall denial rate (KPIs) | `claims`, `underpayment_dollars_by_payer_drg` |
| Underpayment by payer (bar) | `underpayment_dollars_by_payer_drg` |
| Denial rate by payer (bar) | `denial_rate_by_payer` |
| Reimbursement variance by quarter (line) | `reimbursement_variance` |
| Renewal risk (table: days-to-renewal × underpayment × denial) | `renewal_risk` |
| Top DRG leaks (table) | `underpayment_dollars_by_payer_drg` |

To build it: **Dashboards → Create → Add datasets** (one SQL query per view
above), then add the widgets, pick your warehouse, and **Publish**. Because it
reads the same Unity Catalog views, the **PHI masks and the Genie space both sit
on the same governed layer** — the app answers conversationally, the dashboard
answers visually, and AI/BI Dashboards include a built-in Genie "ask" box too.
The same views are equally consumable from **Sigma** if that's your BI standard.
