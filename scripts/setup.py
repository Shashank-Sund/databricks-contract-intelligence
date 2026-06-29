"""One-command setup for Contract Intelligence.

Run this ONCE per workspace, as a user/admin who can create a catalog. It is
safe to re-run (everything is "if not exists" or additive).

What it does (all automatic):
  1. Reads object names from config/app.json.
  2. Creates the Unity Catalog catalog, schema, two Volumes (uploads, exports),
     and the chat_history Delta table.
  3. Finds the app's service principal and grants it everything it needs:
       - USE CATALOG / USE SCHEMA
       - READ/WRITE on both Volumes
       - SELECT/MODIFY on the history table
       - CAN_USE on the SQL warehouse

After this, you only need to deploy the app (see DEPLOY.md).

Usage:
  python scripts/setup.py --app-name contract-intelligence --warehouse-id <sql_warehouse_id>
  (omit --warehouse-id to auto-pick a running serverless warehouse)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from databricks.sdk import WorkspaceClient


def load_cfg() -> dict:
  cfg = json.loads((Path(__file__).resolve().parent.parent / 'config' / 'app.json').read_text())
  uc = cfg.get('uc', {})
  return {
    'catalog': uc.get('catalog', 'genai_chat'),
    'schema': uc.get('schema', 'app'),
    'uploads': uc.get('uploads_volume', 'uploads'),
    'exports': uc.get('exports_volume', 'exports'),
    'table': uc.get('history_table', 'chat_history'),
    'artifacts': uc.get('artifacts_table', 'artifacts'),
    'templates': uc.get('templates_table', 'templates'),
  }


def run_sql(w: WorkspaceClient, warehouse_id: str, sql: str) -> None:
  r = w.statement_execution.execute_statement(
    warehouse_id=warehouse_id, statement=sql, wait_timeout='50s'
  )
  state = str(r.status.state) if (r.status and r.status.state) else 'UNKNOWN'
  if 'SUCCEEDED' not in state:
    msg = (r.status.error.message if (r.status and r.status.error) else '') or ''
    raise SystemExit(f'  ! SQL failed [{state}]: {sql.strip()[:70]}...  {msg}')


def pick_warehouse(w: WorkspaceClient, given: str | None) -> str:
  if given:
    return given
  whs = list(w.warehouses.list())
  running = [x for x in whs if 'RUNNING' in str(x.state)]
  chosen = (running or whs)
  if not chosen:
    raise SystemExit('No SQL warehouse found. Create one or pass --warehouse-id.')
  return chosen[0].id


def main() -> None:
  ap = argparse.ArgumentParser()
  ap.add_argument('--app-name', required=True, help='The Databricks App name (must already be created).')
  ap.add_argument('--warehouse-id', default=None, help='SQL warehouse id (auto-picks one if omitted).')
  ap.add_argument('-p', '--profile', default=None, help='Databricks CLI profile to use.')
  args = ap.parse_args()

  w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
  c = load_cfg()
  cat, sch = c['catalog'], c['schema']
  fq = f'{cat}.{sch}'
  wid = pick_warehouse(w, args.warehouse_id)
  print(f'Using SQL warehouse: {wid}')

  print(f"Resolving the app's service principal for '{args.app_name}'...")
  # Resolve via the REST API (stable across SDK versions; the SDK's AppsAPI
  # method names vary by runtime).
  app = w.api_client.do('GET', f'/api/2.0/apps/{args.app_name}')
  sp = app.get('service_principal_client_id') or app.get('service_principal_id')
  if not sp:
    raise SystemExit('Could not find the app service principal. Create the app first: '
                     f'databricks apps create {args.app_name}')
  print(f'App service principal: {sp}')

  print('Creating Unity Catalog objects (idempotent)...')
  run_sql(w, wid, f'CREATE CATALOG IF NOT EXISTS {cat}')
  run_sql(w, wid, f'CREATE SCHEMA IF NOT EXISTS {fq}')
  run_sql(w, wid, f"CREATE VOLUME IF NOT EXISTS {fq}.{c['uploads']}")
  run_sql(w, wid, f"CREATE VOLUME IF NOT EXISTS {fq}.{c['exports']}")
  run_sql(w, wid, f"""CREATE TABLE IF NOT EXISTS {fq}.{c['table']} (
            id STRING, user_email STRING, conversation_id STRING, title STRING,
            role STRING, content STRING, model STRING, persona STRING,
            turn_id STRING, compare BOOLEAN, created_at TIMESTAMP
          ) USING DELTA""")
  run_sql(w, wid, f"""CREATE TABLE IF NOT EXISTS {fq}.{c['artifacts']} (
            id STRING, user_email STRING, conversation_id STRING, artifact_id STRING,
            version INT, title STRING, type STRING, content STRING,
            subtitle STRING, author STRING, created_at TIMESTAMP
          ) USING DELTA""")
  # Add metadata columns to pre-existing artifacts tables (best-effort; the
  # CREATE above already includes them for fresh installs, so a failure here
  # just means the columns are already present).
  try:
    run_sql(w, wid, f"ALTER TABLE {fq}.{c['artifacts']} ADD COLUMNS (subtitle STRING, author STRING)")
  except SystemExit:
    pass
  run_sql(w, wid, f"""CREATE TABLE IF NOT EXISTS {fq}.{c['templates']} (
            id STRING, user_email STRING, name STRING, volume_path STRING, created_at TIMESTAMP
          ) USING DELTA""")
  print('  created catalog, schema, uploads + exports volumes, chat_history + artifacts tables.')

  print('Granting the app service principal access...')
  for g in [
    f'GRANT USE CATALOG ON CATALOG {cat} TO `{sp}`',
    f'GRANT USE SCHEMA ON SCHEMA {fq} TO `{sp}`',
    f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME {fq}.{c['uploads']} TO `{sp}`",
    f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME {fq}.{c['exports']} TO `{sp}`",
    f"GRANT SELECT, MODIFY ON TABLE {fq}.{c['table']} TO `{sp}`",
    f"GRANT SELECT, MODIFY ON TABLE {fq}.{c['artifacts']} TO `{sp}`",
    f"GRANT SELECT, MODIFY ON TABLE {fq}.{c['templates']} TO `{sp}`",
  ]:
    run_sql(w, wid, g)
  print('  granted UC privileges.')

  print('Granting the app service principal CAN_USE on the warehouse...')
  w.api_client.do(
    'PATCH', f'/api/2.0/permissions/warehouses/{wid}',
    body={'access_control_list': [{'service_principal_name': sp, 'permission_level': 'CAN_USE'}]},
  )
  print('  granted warehouse access.')

  print('\nSETUP COMPLETE. Next: deploy the app (see DEPLOY.md).')
  print('Reminder: the model endpoints in config/app.json must exist and be query-able by')
  print('the app service principal. Built-in Databricks foundation-model endpoints are')
  print('query-able by default. To restrict a model to specific groups, set CAN_QUERY on')
  print('that endpoint (and optionally enable AI Gateway for logging + cost caps).')


if __name__ == '__main__':
  main()
