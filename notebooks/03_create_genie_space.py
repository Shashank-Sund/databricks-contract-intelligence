# Databricks notebook source
# MAGIC %md
# MAGIC # 3. Create a Genie space (the assistant's "data brain") — a guide
# MAGIC
# MAGIC This notebook is mostly a **walkthrough**, not code. A **Genie space** is the
# MAGIC piece that answers number/analytics questions by writing governed SQL over
# MAGIC *your* tables. The app's `genie` tool calls it. You build it once in the
# MAGIC Databricks UI, paste good instructions, grant access, and register its id in
# MAGIC the app config.
# MAGIC
# MAGIC There is one short code cell at the very end to sanity-check that the app's
# MAGIC service principal can query the space.

# COMMAND ----------

# MAGIC %md
# MAGIC ## A. Create the space
# MAGIC
# MAGIC 1. In the left sidebar click **Genie** → **New** (or **+ New space**).
# MAGIC 2. **Pick a warehouse.** Choose any **Serverless** SQL warehouse. (No serverless
# MAGIC    warehouse? Sidebar → **SQL Warehouses** → **Create** → accept defaults →
# MAGIC    **Create**, then come back.)
# MAGIC 3. **Add your tables.** Click **Add tables / data** and select the tables the
# MAGIC    assistant should reason over. For this template that is typically:
# MAGIC    - your **claims / transactions** table, and
# MAGIC    - the **`contract_terms`** table produced by
# MAGIC      `notebooks/01_extract_contract_terms.py`,
# MAGIC    - plus any reporting **views** you have (denial rates, variance, renewal
# MAGIC      risk, etc.).
# MAGIC
# MAGIC    Putting the contract terms in the same space as the claims is what lets the
# MAGIC    space answer questions that join "what we were paid" to "what the contract
# MAGIC    says."
# MAGIC 4. **Name it** something clear, e.g. `Contract Intelligence`.

# COMMAND ----------

# MAGIC %md
# MAGIC ## B. Write strong Instructions  (this is the #1 driver of answer quality)
# MAGIC
# MAGIC In the space settings find the **Instructions** box and paste a curated set.
# MAGIC Bad/empty instructions are the most common cause of wrong answers. A good set:
# MAGIC
# MAGIC - **Defines every metric precisely.** Spell out exactly how a number is
# MAGIC   computed (e.g. *"underpayment = contracted amount minus collected, where
# MAGIC   collected = paid_amount + patient_responsibility; exclude denied claims"*).
# MAGIC - **States the join keys.** Tell Genie how the tables relate (e.g. *"inpatient
# MAGIC   claims join contract_terms on (payer_name, drg_code); outpatient on
# MAGIC   (payer_name, cpt_code)"*).
# MAGIC - **Points to preferred views.** If you built reporting views, tell Genie to
# MAGIC   prefer them over raw aggregation when one fits the question.
# MAGIC - **Handles dates explicitly.** If "renews soon" matters, give it a view that
# MAGIC   does the date math in SQL rather than letting it guess today's date.
# MAGIC
# MAGIC **Template you can adapt:**
# MAGIC
# MAGIC ```
# MAGIC This space answers questions over the <DOMAIN> tables and reporting views.
# MAGIC
# MAGIC Definitions:
# MAGIC - "<metric A>" = <exact formula, in terms of real column names>. Use the
# MAGIC   <view name> view. NEVER <common mistake to avoid>.
# MAGIC - "<metric B>" = <exact formula>. <which rows to include/exclude>.
# MAGIC
# MAGIC Joins:
# MAGIC - <table 1> joins <table 2> on (<key>, <key>).
# MAGIC
# MAGIC Date logic:
# MAGIC - For "<time-based question>", use the <view> view; it computes the date math
# MAGIC   in SQL. Do NOT guess today's date.
# MAGIC
# MAGIC Prefer the reporting views over raw aggregation when one fits the question.
# MAGIC ```
# MAGIC
# MAGIC Save, then ask a couple of test questions and confirm the answers match what
# MAGIC you expect.

# COMMAND ----------

# MAGIC %md
# MAGIC ## C. Grant access so the APP can use the space
# MAGIC
# MAGIC The app must be allowed to run the space. Two cases:
# MAGIC
# MAGIC - **Service-principal auth (`AUTH_MODE=service_principal`):** grant the app's
# MAGIC   **service principal** `CAN RUN` on the space. (You also add the Genie space as
# MAGIC   an app **resource** at deploy time — see `DEPLOY.md`.)
# MAGIC - **On-behalf-of-user auth (`AUTH_MODE=obo`, the default):** *each signed-in
# MAGIC   user* runs the space as themselves, so **every user** needs `CAN RUN` on the
# MAGIC   space **and** the underlying Unity Catalog grants on the tables. (The app's
# MAGIC   service principal still needs `CAN RUN` for the fallback path and for the
# MAGIC   bottom-left "Genie spaces" panel listing.)
# MAGIC
# MAGIC To share: open the space → **Share** (top right) → add the principal/users →
# MAGIC **Can run**.

# COMMAND ----------

# MAGIC %md
# MAGIC ## D. Get the space id and register it in the app config
# MAGIC
# MAGIC 1. Look at the space's web address. It contains `/genie/rooms/<long-id>`. Copy
# MAGIC    that `<long-id>`.
# MAGIC 2. Put it in your config:
# MAGIC    - **Single space (simplest):** set `genie.space_id` in `config/app.json`
# MAGIC      (or the `GENIE_SPACE_ID` env var in `app.yaml`). Every `genie` tool that
# MAGIC      doesn't specify its own space uses this.
# MAGIC    - **Multiple spaces:** give each `genie` tool in `agent.tools[]` its own
# MAGIC      `"space_id"` plus a `description` of what that space covers. The supervisor
# MAGIC      routes each question to the right space by its description. Example:
# MAGIC
# MAGIC ```json
# MAGIC "tools": [
# MAGIC   {
# MAGIC     "name": "query_claims",
# MAGIC     "backend": "genie",
# MAGIC     "space_id": "0123...claims",
# MAGIC     "description": "Claims, payments, denials, underpayments — quantitative SQL.",
# MAGIC     "question_description": "A self-contained data question about claims."
# MAGIC   },
# MAGIC   {
# MAGIC     "name": "query_membership",
# MAGIC     "backend": "genie",
# MAGIC     "space_id": "0123...membership",
# MAGIC     "description": "Enrollment and membership counts by plan and month.",
# MAGIC     "question_description": "A self-contained data question about membership."
# MAGIC   }
# MAGIC ]
# MAGIC ```
# MAGIC
# MAGIC **When added correctly, every accessible space also shows up in the app's
# MAGIC bottom-left "Genie spaces" panel** (that panel lists all spaces the signed-in
# MAGIC user can access; it is independent of which spaces the agent routes to).

# COMMAND ----------

# MAGIC %md
# MAGIC ## E. (Optional) Sanity check: can the service principal query the space?
# MAGIC
# MAGIC Paste your space id below and run this cell **as the app's service principal**
# MAGIC (or as yourself for an OBO check). It uses the Genie Conversation API the app
# MAGIC uses. A non-empty answer means access + instructions are working.

# COMMAND ----------

dbutils.widgets.text("space_id", "<your_genie_space_id>", "Genie space id to test")
dbutils.widgets.text("test_question", "What questions can I ask about this data?", "Test question")

SPACE_ID = dbutils.widgets.get("space_id").strip()
QUESTION = dbutils.widgets.get("test_question").strip()

if SPACE_ID.startswith("<"):
    print("Set the space_id widget to your real Genie space id, then re-run this cell.")
else:
    import time
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    api = w.api_client
    started = api.do("POST", f"/api/2.0/genie/spaces/{SPACE_ID}/start-conversation",
                     body={"content": QUESTION})
    cid = started.get("conversation_id")
    mid = started.get("message_id") or started.get("id")
    print(f"conversation_id={cid} message_id={mid}; polling...")
    msg = {}
    for _ in range(40):
        msg = api.do("GET", f"/api/2.0/genie/spaces/{SPACE_ID}/conversations/{cid}/messages/{mid}")
        if msg.get("status") == "COMPLETED":
            break
        if msg.get("status") in ("FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"):
            print("Genie status:", msg.get("status"))
            break
        time.sleep(3)
    for att in msg.get("attachments", []) or []:
        if att.get("text"):
            print("\nGenie answered:\n", att["text"].get("content"))
        if att.get("query"):
            print("\nGenie SQL:\n", att["query"].get("query"))
