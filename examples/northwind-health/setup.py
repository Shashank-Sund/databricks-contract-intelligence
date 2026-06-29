# Databricks notebook source
# MAGIC %md
# MAGIC # Contract Intelligence — One-Time Setup
# MAGIC
# MAGIC **Run this notebook once.** It builds everything the app needs in *your*
# MAGIC Databricks workspace. You do not need to know Databricks to run it: set the
# MAGIC boxes at the top, then click **Run all** at the top of the screen.
# MAGIC
# MAGIC When it finishes you will have:
# MAGIC
# MAGIC | What | Name it creates |
# MAGIC |---|---|
# MAGIC | A catalog (a top-level data container) | `northwind` |
# MAGIC | A schema (a folder inside the catalog) | `contract_intelligence` |
# MAGIC | A volume (for the contract PDF files) | `contracts` |
# MAGIC | 3 tables (the demo data) | `claims`, `contract_terms`, `contract_chunks` |
# MAGIC | Reporting views (denial rates, underpayments, …) | several |
# MAGIC | A Vector Search index (powers document Q&A) | `contract_chunks_index` |
# MAGIC | *(optional)* PHI masking for a "research analyst" group | `mask_phi` + column masks |
# MAGIC
# MAGIC **Prerequisites** (your Databricks admin can confirm these are on):
# MAGIC - Unity Catalog is enabled (it is, on almost every workspace today).
# MAGIC - A **serverless SQL warehouse** or any cluster running this notebook.
# MAGIC - **Vector Search** is available in your region.
# MAGIC - The Foundation Model endpoint **`databricks-gte-large-en`** exists (it's built in).
# MAGIC
# MAGIC After this notebook, follow `DEPLOY.md` for the 3 clicks that finish the app
# MAGIC (create the Genie space, create the app, paste two IDs).

# COMMAND ----------

# MAGIC %md ### Step 0 — Install the one library this notebook needs
# MAGIC (The Vector Search client. This restarts Python, which is normal —
# MAGIC just let the next cells run.)

# COMMAND ----------

# MAGIC %pip install --quiet databricks-vectorsearch reportlab
dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md ### Step 1 — Settings
# MAGIC The defaults match the rest of the project. Only change them if you have a
# MAGIC reason to. `vs_endpoint` is the Vector Search "server" the index runs on —
# MAGIC leave it blank to auto-pick/create one.

# COMMAND ----------

dbutils.widgets.text("catalog", "northwind", "1. Catalog name")
dbutils.widgets.text("schema", "contract_intelligence", "2. Schema name")
dbutils.widgets.text("volume", "contracts", "3. Volume name (for PDFs)")
dbutils.widgets.text("vs_endpoint", "", "4. Vector Search endpoint (blank = auto)")
dbutils.widgets.dropdown("apply_phi_masking", "yes", ["yes", "no"], "5. Set up PHI masking demo?")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
VOLUME = dbutils.widgets.get("volume").strip()
VS_ENDPOINT = dbutils.widgets.get("vs_endpoint").strip()
APPLY_MASKS = dbutils.widgets.get("apply_phi_masking") == "yes"
EMBEDDING_MODEL = "databricks-gte-large-en"

FQN = f"{CATALOG}.{SCHEMA}"
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
INDEX_NAME = f"{FQN}.contract_chunks_index"
print(f"Will build everything under: {FQN}")
print(f"PDF volume: {VOLUME_PATH}")
print(f"Vector Search index: {INDEX_NAME}")

# COMMAND ----------

# MAGIC %md ### Step 2 — Find the example's data files
# MAGIC This notebook lives in `examples/northwind-health/`, and the pre-built
# MAGIC demo data sits right next to it (`./data/*.parquet`, `./contracts/*.pdf`). We
# MAGIC locate that folder automatically.

# COMMAND ----------

import os

# The notebook path looks like /Workspace/.../<repo>/examples/northwind-health/setup
nb_path = (
    dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
)
EX_DIR = os.path.dirname(nb_path)  # the example folder (this notebook's directory)
DATA_WS = f"/Workspace{EX_DIR}/data"
PDF_WS = f"/Workspace{EX_DIR}/contracts"
print("Example folder:", EX_DIR)
assert os.path.exists(f"{DATA_WS}/claims.parquet"), (
    f"Could not find {DATA_WS}/claims.parquet. Make sure you added this whole repo "
    f"as a Git folder and are running this notebook from inside "
    f"examples/northwind-health/."
)
print("Found the demo data. Good.")

# COMMAND ----------

# MAGIC %md ### Step 3 — Create the catalog, schema, and volume

# COMMAND ----------

spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {FQN}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {FQN}.{VOLUME}")
print(f"Created (or reused) {FQN} and volume '{VOLUME}'.")

# COMMAND ----------

# MAGIC %md ### Step 4 — Load the 3 demo tables
# MAGIC The data is pre-built and fully synthetic (no real patients). We read the
# MAGIC parquet files from the repo and save them as Delta tables.

# COMMAND ----------

import pandas as pd

def load_table(parquet_name, table_name, comment):
    # We read via pandas rather than spark.read.parquet: Serverless Spark rejects
    # parquet INT64 TIMESTAMP(NANOS) with [PARQUET_TYPE_ILLEGAL], and the usual
    # escape hatch (spark.conf "enableVectorizedReader=false") is itself blocked on
    # serverless. pandas reads ns timestamps fine; we downcast them to microseconds
    # (Spark's supported precision) before creating the DataFrame.
    pdf = pd.read_parquet(f"{DATA_WS}/{parquet_name}")
    for col in pdf.columns:
        if str(pdf[col].dtype).startswith("datetime64[ns"):
            pdf[col] = pdf[col].astype("datetime64[us]")
    (spark.createDataFrame(pdf)
         .write.mode("overwrite").option("overwriteSchema", "true")
         .saveAsTable(f"{FQN}.{table_name}"))
    spark.sql(f"COMMENT ON TABLE {FQN}.{table_name} IS '{comment}'")
    n = spark.table(f"{FQN}.{table_name}").count()
    print(f"  {table_name}: {n} rows")

load_table("claims.parquet", "claims",
           "Synthetic 837/835 claim lifecycle. Joins to contract_terms on (payer_name, drg_code) or (payer_name, cpt_code).")
load_table("contract_terms.parquet", "contract_terms",
           "Normalized contract clauses (the ground truth ai_extract produces from the PDFs).")
load_table("contract_chunks.parquet", "contract_chunks",
           "Page-level text chunks of the contract PDFs, indexed by Vector Search for document Q&A.")

# Vector Search delta-sync needs Change Data Feed on the source table.
spark.sql(f"ALTER TABLE {FQN}.contract_chunks SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
print("Enabled Change Data Feed on contract_chunks (required by Vector Search).")

# Chat history table the app writes each conversation turn into (per-user).
spark.sql(f"""
  CREATE TABLE IF NOT EXISTS {FQN}.chat_history (
    id STRING, user_email STRING, conversation_id STRING, title STRING,
    role STRING, content STRING, turn_id STRING, meta STRING,
    created_at TIMESTAMP
  ) USING DELTA
""")
print("Created chat_history table (per-user conversation storage).")

# COMMAND ----------

# MAGIC %md ### Step 5 — Put the contract PDF files into the volume
# MAGIC These are the source agreements (for the `ai_extract` demo and document
# MAGIC viewing). We regenerate them fresh from the generator so the branding always
# MAGIC matches the data; if that ever fails we fall back to the copies in the repo.

# COMMAND ----------

import shutil, sys, subprocess

dst = VOLUME_PATH
pdf_dir = PDF_WS  # default: the copies committed in the repo
try:
    work = "/tmp/contract_gen"
    os.makedirs(work, exist_ok=True)
    gen_src = f"/Workspace{EX_DIR}"
    shutil.copy(f"{gen_src}/generate_contracts.py", work)
    shutil.copy(f"{gen_src}/demo_config.py", work)
    subprocess.run([sys.executable, "generate_contracts.py"], cwd=work, check=True)
    pdf_dir = f"{work}/contracts"
    print("Regenerated contract PDFs from the generator.")
except Exception as e:
    print(f"Regen skipped ({str(e)[:80]}); using the PDFs committed in the repo.")

for fn in sorted(os.listdir(pdf_dir)):
    if fn.lower().endswith(".pdf"):
        dbutils.fs.cp(f"file:{pdf_dir}/{fn}", f"{dst}/{fn}")
print(f"Uploaded contract PDFs to {dst}")
display(dbutils.fs.ls(dst))

# COMMAND ----------

# MAGIC %md ### Step 6 — Create the reporting views
# MAGIC Denial rates, reimbursement variance, the revenue-leakage view, etc. These
# MAGIC are what the Genie space answers questions from.

# COMMAND ----------

sql_text = open(f"/Workspace{EX_DIR}/metric_views.sql").read()
sql_text = sql_text.replace("{catalog}", CATALOG).replace("{schema}", SCHEMA)


def split_statements(text):
    stmts, buf, in_dollar = [], [], False
    for line in text.splitlines():
        if "$$" in line and line.count("$$") % 2 == 1:
            in_dollar = not in_dollar
        buf.append(line)
        if not in_dollar and line.rstrip().endswith(";"):
            stmts.append("\n".join(buf)); buf = []
    if buf and "".join(buf).strip():
        stmts.append("\n".join(buf))
    return stmts


for stmt in split_statements(sql_text):
    body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip().rstrip(";")
    if not body:
        continue
    try:
        spark.sql(body)
        print("  ran:", body.splitlines()[0][:70])
    except Exception as e:
        print(f"  WARN: {str(e)[:120]}")

# COMMAND ----------

# MAGIC %md ### Step 7 — Create the Vector Search index
# MAGIC This powers the contract-document Q&A (the RAG tool). It can take a few
# MAGIC minutes to come online the first time — that's normal.

# COMMAND ----------

from databricks.vector_search.client import VectorSearchClient

vsc = VectorSearchClient(disable_notice=True)

# Pick an endpoint: use the one you named, else find an existing online one, else create.
endpoint = VS_ENDPOINT
if not endpoint:
    existing = [e["name"] for e in (vsc.list_endpoints().get("endpoints") or [])]
    endpoint = existing[0] if existing else "contract_intelligence_vs"
    if endpoint not in existing:
        print(f"Creating Vector Search endpoint '{endpoint}' (one-time, ~5 min)...")
        vsc.create_endpoint_and_wait(name=endpoint, endpoint_type="STANDARD")
print(f"Using Vector Search endpoint: {endpoint}")

try:
    vsc.create_delta_sync_index_and_wait(
        endpoint_name=endpoint,
        index_name=INDEX_NAME,
        source_table_name=f"{FQN}.contract_chunks",
        pipeline_type="TRIGGERED",
        primary_key="chunk_id",
        embedding_source_column="text",
        embedding_model_endpoint_name=EMBEDDING_MODEL,
    )
    print(f"Created index {INDEX_NAME}")
except Exception as e:
    if "already exists" in str(e).lower():
        print("Index already exists; syncing latest rows...")
        vsc.get_index(endpoint, INDEX_NAME).sync()
    else:
        raise

print(f"\n>>> Put this in config/app.json under rag.vector_search_index:\n    {INDEX_NAME}")
print(f">>> ...and the Vector Search endpoint name is: {endpoint}")

# COMMAND ----------

# MAGIC %md ### Step 8 — (Optional) PHI masking for the governance demo
# MAGIC This shows how Unity Catalog hides sensitive columns from one group while
# MAGIC another group sees everything. It only runs if you chose **yes** at the top,
# MAGIC and only fully works once the two account groups exist (see DEPLOY.md →
# MAGIC "Governance demo"). If the groups don't exist yet, this still creates the
# MAGIC mask; it just treats everyone as "not a BI analyst" until the group is made.

# COMMAND ----------

if APPLY_MASKS:
    spark.sql(f"""
      CREATE OR REPLACE FUNCTION {FQN}.mask_phi(val STRING) RETURNS STRING
      RETURN CASE WHEN is_account_group_member('northwind_bi_analysts') THEN val ELSE 'REDACTED' END
    """)
    spark.sql(f"GRANT EXECUTE ON FUNCTION {FQN}.mask_phi TO `account users`")
    for col in ["member_id", "patient_id", "check_eft_number"]:
        spark.sql(f"ALTER TABLE {FQN}.claims ALTER COLUMN {col} SET MASK {FQN}.mask_phi")
        print(f"  masked claims.{col}")
    print("PHI masking applied. BI analysts see full values; everyone else sees REDACTED.")
else:
    print("Skipped PHI masking (you chose 'no').")

# COMMAND ----------

# MAGIC %md ### Done — quick check
# MAGIC These should return data. If they do, the data layer is ready and you can
# MAGIC move to `DEPLOY.md`.

# COMMAND ----------

print("Denial rate by payer:")
display(spark.sql(f"SELECT * FROM {FQN}.denial_rate_by_payer ORDER BY denial_rate DESC"))
print("Largest underpayments (revenue leakage):")
display(spark.sql(f"SELECT * FROM {FQN}.underpayment_dollars_by_payer_drg ORDER BY underpayment_dollars DESC LIMIT 5"))
