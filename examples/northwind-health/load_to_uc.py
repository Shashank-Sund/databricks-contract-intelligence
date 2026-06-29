# Databricks notebook source
# =====================================================================
# load_to_uc.py
# Loads the synthetic contract-intelligence demo assets into Unity Catalog.
#
# Run this AS A DATABRICKS NOTEBOOK (or with Databricks Connect) once workspace
# auth is available. It is idempotent: re-running drops/replaces nothing
# destructively except the demo tables/views it owns.
#
# It will:
#   1. Create the catalog, schema, and a managed Volume.
#   2. Upload the contract + amendment PDFs into the Volume.
#   3. Create the `claims` and `contract_terms` Delta tables from the parquet.
#   4. Create the metric views from metric_views.sql.
#
# Parameters (Databricks widgets, with defaults):
#   catalog = northwind
#   schema  = contract_intelligence
#   volume  = contracts
# =====================================================================

# COMMAND ----------

import os

try:
    dbutils.widgets.text("catalog", "northwind")
    dbutils.widgets.text("schema", "contract_intelligence")
    dbutils.widgets.text("volume", "contracts")
    CATALOG = dbutils.widgets.get("catalog")
    SCHEMA = dbutils.widgets.get("schema")
    VOLUME = dbutils.widgets.get("volume")
except NameError:
    # Running outside a notebook (e.g. via Databricks Connect)
    CATALOG = os.environ.get("DEMO_CATALOG", "northwind")
    SCHEMA = os.environ.get("DEMO_SCHEMA", "contract_intelligence")
    VOLUME = os.environ.get("DEMO_VOLUME", "contracts")

# Local source directory (the folder that contains this script + ./data + ./contracts).
# When run as a Databricks notebook from a Repo/workspace path, set LOCAL_DIR to that path.
LOCAL_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else "."
DATA_DIR = os.path.join(LOCAL_DIR, "data")
CONTRACTS_DIR = os.path.join(LOCAL_DIR, "contracts")

VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"

print(f"Target: {CATALOG}.{SCHEMA}  volume={VOLUME_PATH}")

# COMMAND ----------

# 1. Catalog / schema / volume -----------------------------------------
spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME}")
spark.sql(f"COMMENT ON VOLUME {CATALOG}.{SCHEMA}.{VOLUME} IS "
          f"'Source payer contract + amendment PDFs for ai_parse_document / ai_extract.'")

# COMMAND ----------

# 2. Upload contract PDFs into the Volume ------------------------------
#    dbutils.fs.cp works from the driver-local filesystem ("file:") to the Volume.
contract_dst = f"{VOLUME_PATH}/source_pdfs"
try:
    dbutils.fs.mkdirs(contract_dst)
    for fn in sorted(os.listdir(CONTRACTS_DIR)):
        if fn.lower().endswith(".pdf"):
            src = f"file:{os.path.join(CONTRACTS_DIR, fn)}"
            dbutils.fs.cp(src, f"{contract_dst}/{fn}")
            print(f"  uploaded {fn}")
except NameError:
    # No dbutils (Connect): use the Files API / workspace client instead.
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    for fn in sorted(os.listdir(CONTRACTS_DIR)):
        if fn.lower().endswith(".pdf"):
            with open(os.path.join(CONTRACTS_DIR, fn), "rb") as f:
                w.files.upload(f"{contract_dst}/{fn}", f, overwrite=True)
            print(f"  uploaded {fn}")

# COMMAND ----------

# 3. Delta tables from parquet -----------------------------------------
#    Read via pandas, not spark.read.parquet: Serverless Spark rejects parquet
#    INT64 TIMESTAMP(NANOS) ([PARQUET_TYPE_ILLEGAL]) and the vectorized-reader
#    config workaround is blocked on serverless. We downcast ns timestamps to
#    microseconds (Spark's supported precision) before createDataFrame.
import pandas as pd

def _write_delta(parquet_path, table_name):
    pdf = pd.read_parquet(parquet_path)
    for col in pdf.columns:
        if str(pdf[col].dtype).startswith("datetime64[ns"):
            pdf[col] = pdf[col].astype("datetime64[us]")
    (spark.createDataFrame(pdf)
          .write.mode("overwrite").option("overwriteSchema", "true")
          .saveAsTable(f"{CATALOG}.{SCHEMA}.{table_name}"))
    print(f"  wrote table {CATALOG}.{SCHEMA}.{table_name}")

_write_delta(os.path.join(DATA_DIR, 'claims.parquet'), "claims")
_write_delta(os.path.join(DATA_DIR, 'contract_terms.parquet'), "contract_terms")

spark.sql(f"COMMENT ON TABLE {CATALOG}.{SCHEMA}.claims IS "
          f"'Synthetic 837/835 claim lifecycle. Joins to contract_terms on (payer_name, drg_code) or (payer_name, cpt_code).'")
spark.sql(f"COMMENT ON TABLE {CATALOG}.{SCHEMA}.contract_terms IS "
          f"'Normalized contract clauses (ground truth of ai_extract over the PDFs in the Volume).'")

# COMMAND ----------

# 4. Metric views ------------------------------------------------------
#    Reads metric_views.sql, substitutes placeholders, runs each statement.
sql_path = os.path.join(LOCAL_DIR, "metric_views.sql")
with open(sql_path) as f:
    ddl = f.read()
ddl = ddl.replace("{catalog}", CATALOG).replace("{schema}", SCHEMA)

# Split on ';' at statement boundaries. The metric view uses a $$ ... $$ body,
# so split carefully: temporarily protect the dollar-quoted block.
import re

def split_statements(text):
    stmts, buf, in_dollar = [], [], False
    for line in text.splitlines():
        if "$$" in line:
            in_dollar = not in_dollar if line.count("$$") % 2 == 1 else in_dollar
        buf.append(line)
        if not in_dollar and line.rstrip().endswith(";"):
            stmts.append("\n".join(buf))
            buf = []
    if buf and "".join(buf).strip():
        stmts.append("\n".join(buf))
    return [s for s in stmts if s.strip() and not s.strip().startswith("--")]

for stmt in split_statements(ddl):
    # skip pure-comment chunks
    body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
    if not body:
        continue
    try:
        spark.sql(stmt)
        first = body.splitlines()[0][:70]
        print(f"  ran: {first}")
    except Exception as e:
        print(f"  WARN failed (may need metric-view-capable runtime): {e}")

# COMMAND ----------

print("Done. Validate with:")
print(f"  SELECT * FROM {CATALOG}.{SCHEMA}.underpayment_dollars_by_payer_drg LIMIT 20;")
print(f"  SELECT * FROM {CATALOG}.{SCHEMA}.denial_rate_by_payer ORDER BY denial_rate DESC;")
