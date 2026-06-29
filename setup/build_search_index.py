# Databricks notebook source
# MAGIC %md
# MAGIC # Build a document search index (generic RAG setup)
# MAGIC
# MAGIC Turns a folder of documents in a Unity Catalog **Volume** into a **Vector
# MAGIC Search index** the app's `vector_search` tool can query. This is the reusable
# MAGIC RAG pipeline: point it at your documents, get an index. Run with **Run all**.
# MAGIC
# MAGIC Set the five boxes below, then put the resulting index name into your config's
# MAGIC `rag.vector_search_index`.

# COMMAND ----------

# MAGIC %pip install --quiet databricks-vectorsearch
dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("volume_path", "/Volumes/<catalog>/<schema>/<volume>", "1. Volume folder with your documents")
dbutils.widgets.text("chunks_table", "<catalog>.<schema>.doc_chunks", "2. Output table for the text chunks")
dbutils.widgets.text("index_name", "<catalog>.<schema>.doc_chunks_index", "3. Vector Search index to create")
dbutils.widgets.text("vs_endpoint", "", "4. Vector Search endpoint (blank = auto)")
dbutils.widgets.text("embedding_model", "databricks-gte-large-en", "5. Embedding model endpoint")

VOLUME = dbutils.widgets.get("volume_path").strip()
CHUNKS = dbutils.widgets.get("chunks_table").strip()
INDEX = dbutils.widgets.get("index_name").strip()
VS_ENDPOINT = dbutils.widgets.get("vs_endpoint").strip()
EMBED = dbutils.widgets.get("embedding_model").strip()
print(f"{VOLUME}  ->  {CHUNKS}  ->  {INDEX}")

# COMMAND ----------

# MAGIC %md ### 1. Parse the documents into page-level text chunks
# MAGIC `ai_parse_document` extracts text elements with their page numbers; we group
# MAGIC them into one chunk per page (`<file>__p<page>`).

# COMMAND ----------

spark.sql(f"""
  CREATE OR REPLACE TABLE {CHUNKS} AS
  WITH parsed AS (
    SELECT _metadata.file_name AS source_file, ai_parse_document(content) AS p
    FROM READ_FILES('{VOLUME}', format => 'binaryFile')
  ),
  elems AS (
    SELECT source_file,
           CAST(ve.value:bbox[0]:page_id AS INT) AS page_id,
           CAST(ve.value:content AS STRING) AS content,
           ve.pos AS ord
    FROM parsed, LATERAL variant_explode(p:document:elements) AS ve
  )
  SELECT concat(source_file, '__p', page_id) AS chunk_id,
         source_file,
         page_id,
         concat_ws('\\n', array_agg(content) WITHIN GROUP (ORDER BY ord)) AS text
  FROM elems
  WHERE content IS NOT NULL AND page_id IS NOT NULL
  GROUP BY source_file, page_id
""")
# Vector Search delta-sync requires Change Data Feed.
spark.sql(f"ALTER TABLE {CHUNKS} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
print("chunks:", spark.table(CHUNKS).count())
display(spark.sql(f"SELECT chunk_id, source_file, page_id, left(text, 80) AS preview FROM {CHUNKS} LIMIT 5"))

# COMMAND ----------

# MAGIC %md ### 2. Create the Vector Search index (delta-sync, triggered)

# COMMAND ----------

from databricks.vector_search.client import VectorSearchClient

vsc = VectorSearchClient(disable_notice=True)
endpoint = VS_ENDPOINT
if not endpoint:
    existing = [e["name"] for e in (vsc.list_endpoints().get("endpoints") or [])]
    endpoint = existing[0] if existing else "doc_search_vs"
    if endpoint not in existing:
        print(f"Creating endpoint '{endpoint}' (~5 min)...")
        vsc.create_endpoint_and_wait(name=endpoint, endpoint_type="STANDARD")
print("endpoint:", endpoint)

try:
    vsc.create_delta_sync_index_and_wait(
        endpoint_name=endpoint,
        index_name=INDEX,
        source_table_name=CHUNKS,
        pipeline_type="TRIGGERED",
        primary_key="chunk_id",
        embedding_source_column="text",
        embedding_model_endpoint_name=EMBED,
    )
    print(f"Created index {INDEX}")
except Exception as e:
    if "already exists" in str(e).lower():
        vsc.get_index(endpoint, INDEX).sync()
        print(f"Index existed; re-synced {INDEX}")
    else:
        raise

print(f"\n>>> Put this in your config under rag.vector_search_index:\n    {INDEX}")
