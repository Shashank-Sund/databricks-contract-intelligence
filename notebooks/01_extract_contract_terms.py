# Databricks notebook source
# MAGIC %md
# MAGIC # 1. Extract structured contract terms from your PDFs
# MAGIC
# MAGIC **What this does, in plain English:** you have a folder of contract (or other)
# MAGIC documents sitting in a Unity Catalog **Volume**. This notebook reads each PDF,
# MAGIC uses Databricks AI functions to pull out the specific facts you care about
# MAGIC (e.g. timely-filing window, renewal date, whether prior authorization is
# MAGIC required), and writes them into one tidy **Delta table** — one row per file.
# MAGIC
# MAGIC That table is meant to live **next to your claims/transaction tables in a
# MAGIC Genie space**, so the assistant can answer questions that mix the numbers
# MAGIC (claims) with the contract facts (this table).
# MAGIC
# MAGIC You do **not** need to know Databricks to run this. Set the boxes at the top,
# MAGIC edit the list of terms in **Step 3** if you like, then click **Run all**.
# MAGIC
# MAGIC **Prerequisites** (your admin can confirm):
# MAGIC - Unity Catalog is enabled (it is on almost every workspace).
# MAGIC - Your documents are already uploaded to a UC **Volume** (a folder for files).
# MAGIC - `ai_parse_document` and `ai_extract` are available in your region (they run
# MAGIC   on serverless SQL; no model deployment needed).

# COMMAND ----------

# MAGIC %md ### Step 1 — Settings
# MAGIC Fill these in. `volume_path` is the folder that holds your PDF files.

# COMMAND ----------

dbutils.widgets.text("catalog", "<your_catalog>", "1. Catalog name")
dbutils.widgets.text("schema", "<your_schema>", "2. Schema name")
dbutils.widgets.text("volume_path", "/Volumes/<your_catalog>/<your_schema>/<your_volume>", "3. Volume folder with your contract PDFs")
dbutils.widgets.text("output_table", "contract_terms", "4. Output table name")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
VOLUME_PATH = dbutils.widgets.get("volume_path").strip()
OUTPUT_TABLE = dbutils.widgets.get("output_table").strip()

FQ_TABLE = f"{CATALOG}.{SCHEMA}.{OUTPUT_TABLE}"
print(f"Reading PDFs from: {VOLUME_PATH}")
print(f"Will write extracted terms to: {FQ_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 2 — Make sure the catalog/schema exist

# COMMAND ----------

spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
print(f"Using {CATALOG}.{SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 3 — Define the terms to extract  *(EDIT THIS)*
# MAGIC
# MAGIC This is the part you change. Each entry is a field name plus a short, plain
# MAGIC description of what to look for. `ai_extract` uses the descriptions to find
# MAGIC the value in each document. Add, remove, or reword freely — keep the field
# MAGIC names short and lowercase (they become table columns).
# MAGIC
# MAGIC The defaults below are a healthcare payer-contract example; replace them with
# MAGIC whatever your documents contain.

# COMMAND ----------

# ----------------------------------------------------------------------------
# EDIT ME: the contract terms to pull out of each document.
#   key   = the column name in the output table
#   value = a plain-English hint telling ai_extract what to look for
# ----------------------------------------------------------------------------
CONTRACT_TERMS = {
    "payer_name": "the insurance company / payer or counterparty name",
    "reimbursement_methodology": "how payment is calculated, e.g. percent of Medicare, per-DRG case rate, fee schedule",
    "timely_filing_days": "the number of days the provider has to submit a claim (timely filing window)",
    "appeal_window_days": "the number of days allowed to appeal a denied claim",
    "prior_authorization_required": "whether prior authorization is required (yes or no)",
    "effective_date": "the contract effective / start date",
    "renewal_date": "the renewal or non-renewal notice date",
    "termination_date": "the contract termination / end date",
}

# The list of field-name strings passed to ai_extract.
TERM_KEYS = list(CONTRACT_TERMS.keys())
print("Extracting these fields from each document:")
for k, v in CONTRACT_TERMS.items():
    print(f"  - {k}: {v}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 4 — Parse the PDFs to text
# MAGIC `ai_parse_document` turns each PDF into machine-readable text. We keep the
# MAGIC file name so every row is traceable back to its source document.

# COMMAND ----------

PARSED_TMP = f"{CATALOG}.{SCHEMA}.{OUTPUT_TABLE}__parsed_tmp"

spark.sql(f"""
  CREATE OR REPLACE TABLE {PARSED_TMP} AS
  SELECT
    _metadata.file_name AS source_file,
    -- Flatten every parsed element's text into one document string per file.
    ai_parse_document(content) AS parsed
  FROM READ_FILES('{VOLUME_PATH}', format => 'binaryFile')
""")

# Reduce the parsed structure to one plain-text blob per file.
spark.sql(f"""
  CREATE OR REPLACE TABLE {PARSED_TMP} AS
  WITH elems AS (
    SELECT source_file,
           CAST(ve.value:content AS STRING) AS content,
           ve.pos AS ord
    FROM {PARSED_TMP}, LATERAL variant_explode(parsed:document:elements) AS ve
  )
  SELECT source_file,
         concat_ws('\\n', array_agg(content) WITHIN GROUP (ORDER BY ord)) AS doc_text
  FROM elems
  WHERE content IS NOT NULL
  GROUP BY source_file
""")

print("Parsed documents:", spark.table(PARSED_TMP).count())
display(spark.sql(f"SELECT source_file, left(doc_text, 120) AS preview FROM {PARSED_TMP} LIMIT 5"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 5 — Extract the terms with `ai_extract`
# MAGIC We pass the document text and the list of field names you defined above.
# MAGIC `ai_extract` returns a struct with one value per field; we expand it into
# MAGIC real columns and save the result.

# COMMAND ----------

# Build the SQL array literal of field names for ai_extract, e.g. ARRAY('payer_name', ...).
fields_sql = ", ".join("'" + k.replace("'", "") + "'" for k in TERM_KEYS)
# Build the SELECT list that pulls each field out of the returned struct.
cols_sql = ",\n         ".join(f"extracted['{k}'] AS {k}" for k in TERM_KEYS)

spark.sql(f"""
  CREATE OR REPLACE TABLE {FQ_TABLE} AS
  WITH x AS (
    SELECT source_file,
           ai_extract(doc_text, ARRAY({fields_sql})) AS extracted
    FROM {PARSED_TMP}
  )
  SELECT source_file,
         {cols_sql}
  FROM x
""")

spark.sql(f"COMMENT ON TABLE {FQ_TABLE} IS "
          f"'Structured contract terms extracted from the source PDFs via ai_parse_document + ai_extract. One row per document. Add this to your Genie space alongside your claims/transaction tables.'")

print(f"Wrote {spark.table(FQ_TABLE).count()} rows to {FQ_TABLE}")
display(spark.table(FQ_TABLE))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 6 — Clean up the temp table

# COMMAND ----------

spark.sql(f"DROP TABLE IF EXISTS {PARSED_TMP}")
print("Done.")
print(f">>> Next: add {FQ_TABLE} to your Genie space (see notebooks/03_create_genie_space.py),")
print(">>> alongside your claims/transaction tables, so the assistant can answer mixed questions.")
