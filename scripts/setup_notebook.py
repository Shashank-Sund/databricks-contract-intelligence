# Databricks notebook source
# MAGIC %md
# MAGIC # Contract Intelligence , one-time setup (run inside Databricks)
# MAGIC
# MAGIC Run this notebook **once**, in the same workspace where the app is deployed,
# MAGIC as a user who can create a catalog (a workspace/metastore admin). It is the
# MAGIC in-Databricks equivalent of `scripts/setup.py`, so you never need the CLI or
# MAGIC a local machine.
# MAGIC
# MAGIC **What it does (all automatic, safe to re-run):**
# MAGIC 1. Reads object names from `config/app.json` (or uses the defaults below).
# MAGIC 2. Creates the Unity Catalog catalog, schema, the `uploads` + `exports`
# MAGIC    Volumes, and the `chat_history` Delta table.
# MAGIC 3. Finds the app's service principal and grants it everything it needs
# MAGIC    (USE CATALOG/SCHEMA, READ/WRITE on both Volumes, SELECT/MODIFY on the
# MAGIC    history table, and CAN_USE on the SQL warehouse).
# MAGIC
# MAGIC **Before you run:** create the app first (Compute -> Apps -> Create app), so
# MAGIC its service principal exists. Then set the widgets below and `Run all`.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 1 , set these two values
# MAGIC - **app_name**: the exact name of the Databricks App you created.
# MAGIC - **warehouse_id**: a serverless SQL warehouse id (Compute -> SQL Warehouses
# MAGIC   -> your warehouse -> the id at the end of the URL). Leave blank to auto-pick
# MAGIC   a running one.

# COMMAND ----------

dbutils.widgets.text('app_name', 'contract-intelligence', 'Databricks App name')
dbutils.widgets.text('warehouse_id', '', 'SQL warehouse id (blank = auto-pick)')

app_name = dbutils.widgets.get('app_name').strip()
warehouse_id = dbutils.widgets.get('warehouse_id').strip()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 2 , read the config (names of the catalog/schema/volumes/table)
# MAGIC These come from `config/app.json` so they always match what the app expects.
# MAGIC If the file can't be found (e.g. you're running this notebook outside the Git
# MAGIC folder), it falls back to the defaults shown here.

# COMMAND ----------

import json
from pathlib import Path

DEFAULTS = {
  'catalog': 'genai_chat',
  'schema': 'app',
  'uploads': 'uploads',
  'exports': 'exports',
  'table': 'chat_history',
  'artifacts': 'artifacts',
  'templates': 'templates',
}


def load_cfg() -> dict:
  # Try a few likely locations for config/app.json relative to this notebook.
  here = Path.cwd()
  candidates = [
    here / 'config' / 'app.json',
    here.parent / 'config' / 'app.json',
    here / '..' / 'config' / 'app.json',
  ]
  for p in candidates:
    try:
      if p.exists():
        uc = json.loads(p.read_text()).get('uc', {})
        print(f'Loaded config from: {p}')
        return {
          'catalog': uc.get('catalog', DEFAULTS['catalog']),
          'schema': uc.get('schema', DEFAULTS['schema']),
          'uploads': uc.get('uploads_volume', DEFAULTS['uploads']),
          'exports': uc.get('exports_volume', DEFAULTS['exports']),
          'table': uc.get('history_table', DEFAULTS['table']),
          'artifacts': uc.get('artifacts_table', DEFAULTS['artifacts']),
          'templates': uc.get('templates_table', DEFAULTS['templates']),
        }
    except Exception as e:
      print(f'  (could not read {p}: {e})')
  print('config/app.json not found, using defaults. Edit the widgets/DEFAULTS if your config differs.')
  return dict(DEFAULTS)


c = load_cfg()
cat, sch = c['catalog'], c['schema']
fq = f'{cat}.{sch}'
print('Will create / grant on:')
print(f'  catalog : {cat}')
print(f'  schema  : {fq}')
print(f"  volumes : {fq}.{c['uploads']}, {fq}.{c['exports']}")
print(f"  table   : {fq}.{c['table']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 3 , find the app's service principal and the warehouse

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# Resolve via the REST API (stable across SDK versions; the SDK's AppsAPI
# method names vary by runtime).
app = w.api_client.do('GET', f'/api/2.0/apps/{app_name}')
sp = app.get('service_principal_client_id') or app.get('service_principal_id')
if not sp:
  raise SystemExit(
    f"Could not find a service principal for app '{app_name}'. "
    'Create the app first (Compute -> Apps -> Create app), then re-run.'
  )
print(f'App service principal: {sp}')

if not warehouse_id:
  whs = list(w.warehouses.list())
  running = [x for x in whs if 'RUNNING' in str(x.state)]
  chosen = running or whs
  if not chosen:
    raise SystemExit('No SQL warehouse found. Create one, then put its id in the warehouse_id widget.')
  warehouse_id = chosen[0].id
print(f'Using SQL warehouse: {warehouse_id}')

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 4 , create the Unity Catalog objects (idempotent)

# COMMAND ----------

spark.sql(f'CREATE CATALOG IF NOT EXISTS {cat}')
spark.sql(f'CREATE SCHEMA IF NOT EXISTS {fq}')
spark.sql(f"CREATE VOLUME IF NOT EXISTS {fq}.{c['uploads']}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {fq}.{c['exports']}")
spark.sql(f"""CREATE TABLE IF NOT EXISTS {fq}.{c['table']} (
  id STRING, user_email STRING, conversation_id STRING, title STRING,
  role STRING, content STRING, model STRING, persona STRING,
  turn_id STRING, compare BOOLEAN, created_at TIMESTAMP
) USING DELTA""")
spark.sql(f"""CREATE TABLE IF NOT EXISTS {fq}.{c['artifacts']} (
  id STRING, user_email STRING, conversation_id STRING, artifact_id STRING,
  version INT, title STRING, type STRING, content STRING,
  subtitle STRING, author STRING, created_at TIMESTAMP
) USING DELTA""")
try:
  spark.sql(f"ALTER TABLE {fq}.{c['artifacts']} ADD COLUMNS (subtitle STRING, author STRING)")
except Exception:
  pass  # columns already present (fresh installs get them from CREATE above)
spark.sql(f"""CREATE TABLE IF NOT EXISTS {fq}.{c['templates']} (
  id STRING, user_email STRING, name STRING, volume_path STRING, created_at TIMESTAMP
) USING DELTA""")
print('Created catalog, schema, uploads + exports volumes, and the chat_history + artifacts tables.')

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 5 , grant the app's service principal access

# COMMAND ----------

grants = [
  f'GRANT USE CATALOG ON CATALOG {cat} TO `{sp}`',
  f'GRANT USE SCHEMA ON SCHEMA {fq} TO `{sp}`',
  f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME {fq}.{c['uploads']} TO `{sp}`",
  f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME {fq}.{c['exports']} TO `{sp}`",
  f"GRANT SELECT, MODIFY ON TABLE {fq}.{c['table']} TO `{sp}`",
  f"GRANT SELECT, MODIFY ON TABLE {fq}.{c['artifacts']} TO `{sp}`",
  f"GRANT SELECT, MODIFY ON TABLE {fq}.{c['templates']} TO `{sp}`",
]
for g in grants:
  spark.sql(g)
print('Granted Unity Catalog privileges to the app service principal.')

# Grant the app service principal CAN_USE on the SQL warehouse.
w.api_client.do(
  'PATCH', f'/api/2.0/permissions/warehouses/{warehouse_id}',
  body={'access_control_list': [{'service_principal_name': sp, 'permission_level': 'CAN_USE'}]},
)
print('Granted CAN_USE on the SQL warehouse.')

# COMMAND ----------

# MAGIC %md
# MAGIC ### Done
# MAGIC Setup is complete. Go back to your app (Compute -> Apps -> your app) and
# MAGIC **redeploy / restart** it so it picks up the new access. Then open the app URL.
# MAGIC
# MAGIC **Note on models:** the serving endpoints listed in `config/app.json` must
# MAGIC exist and be query-able by the app's service principal. Built-in Databricks
# MAGIC foundation-model endpoints are query-able by default. To restrict a model to
# MAGIC specific groups, set CAN QUERY on that endpoint (and optionally enable AI
# MAGIC Gateway on it for logging, rate limits, and cost caps).
