"""Lakebase (managed Postgres) backend for chat history.

Activated when HISTORY_BACKEND=lakebase. Lakebase uses Databricks identity for
auth: the Postgres password is a short-lived Databricks OAuth token. There are
two ways to connect, in priority order:

  1. LAKEBASE_PG_URL - a full postgresql:// URL (host/db baked in). The password
     in the URL is ignored; we always inject a fresh Databricks OAuth token as
     the password so connections never expire mid-demo.
  2. LAKEBASE_INSTANCE (+ config history.lakebase.{database,schema}) - we resolve
     the instance's read_write_dns via the Database Instances API and mint a
     credential, both using the app's Databricks auth (SDK default chain).

Schema is created lazily on first use (scripts/setup_lakebase.py does the same
up front). Public API mirrors the Delta store. psycopg (v3) preferred,
psycopg2 fallback.

NOTE for the demo: the default backend is Delta (history_store.py), which needs
no Postgres. This module is here so the app is genuinely Lakebase-capable; flip
HISTORY_BACKEND=lakebase once an instance exists.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from ..config_loader import config_loader

logger = logging.getLogger(__name__)

_INSTANCE_DNS_CACHE: dict[str, str] = {}


def _lakebase_cfg() -> dict:
  return (config_loader.app_config.get('history', {}) or {}).get('lakebase', {}) or {}


def _schema() -> str:
  return os.environ.get('LAKEBASE_SCHEMA') or _lakebase_cfg().get('schema', 'chat_history')


def _oauth_token() -> str:
  """A fresh Databricks OAuth token (used as the Postgres password)."""
  from databricks.sdk import WorkspaceClient

  ws = WorkspaceClient()
  return ws.config.authenticate().get('Authorization', '').replace('Bearer ', '').strip()


def _resolve_instance_dns(instance: str) -> str:
  if instance in _INSTANCE_DNS_CACHE:
    return _INSTANCE_DNS_CACHE[instance]
  from databricks.sdk import WorkspaceClient

  ws = WorkspaceClient()
  info = ws.api_client.do('GET', f'/api/2.0/database/instances/{instance}')
  dns = info.get('read_write_dns')
  if not dns:
    raise RuntimeError(f'Lakebase instance {instance} has no read_write_dns yet.')
  _INSTANCE_DNS_CACHE[instance] = dns
  return dns


def _conn_params() -> dict:
  """Return psycopg connection kwargs with a fresh token as password."""
  token = _oauth_token()
  url = os.environ.get('LAKEBASE_PG_URL')
  if url:
    p = urlparse(url)
    return {
      'host': p.hostname,
      'port': p.port or 5432,
      'dbname': (p.path or '/databricks_postgres').lstrip('/') or 'databricks_postgres',
      'user': p.username or os.environ.get('DATABRICKS_USER_EMAIL', 'token'),
      'password': token,
      'sslmode': 'require',
    }
  instance = os.environ.get('LAKEBASE_INSTANCE') or _lakebase_cfg().get('instance')
  if not instance:
    raise RuntimeError('No LAKEBASE_PG_URL and no LAKEBASE_INSTANCE/config.history.lakebase.instance.')
  dns = _resolve_instance_dns(instance)
  user = os.environ.get('LAKEBASE_USER') or os.environ.get('DATABRICKS_CLIENT_ID') or 'token'
  return {
    'host': dns,
    'port': 5432,
    'dbname': os.environ.get('LAKEBASE_DATABASE') or _lakebase_cfg().get('database', 'databricks_postgres'),
    'user': user,
    'password': token,
    'sslmode': 'require',
  }


def _connect():
  params = _conn_params()
  try:
    import psycopg  # psycopg3
    return psycopg.connect(**params)
  except ImportError:
    import psycopg2
    return psycopg2.connect(**params)


def ensure_schema() -> None:
  """Create the schema + tables if absent. Safe to call repeatedly."""
  sch = _schema()
  ddl = [
    f'CREATE SCHEMA IF NOT EXISTS {sch}',
    f'''CREATE TABLE IF NOT EXISTS {sch}.conversations (
          conversation_id TEXT PRIMARY KEY,
          user_email TEXT NOT NULL,
          title TEXT,
          created_at TIMESTAMPTZ DEFAULT now(),
          last_at TIMESTAMPTZ DEFAULT now()
        )''',
    f'''CREATE TABLE IF NOT EXISTS {sch}.messages (
          id TEXT PRIMARY KEY,
          conversation_id TEXT NOT NULL,
          user_email TEXT NOT NULL,
          role TEXT NOT NULL,
          content TEXT,
          turn_id TEXT,
          meta TEXT,
          created_at TIMESTAMPTZ DEFAULT now()
        )''',
    f'CREATE INDEX IF NOT EXISTS messages_conv_idx ON {sch}.messages (conversation_id, created_at)',
    f'CREATE INDEX IF NOT EXISTS conv_user_idx ON {sch}.conversations (user_email, last_at DESC)',
  ]
  conn = _connect()
  try:
    with conn.cursor() as cur:
      for stmt in ddl:
        cur.execute(stmt)
    conn.commit()
  finally:
    conn.close()


async def save_message(
  *, user_email: str, conversation_id: str, role: str, content: str,
  title: str = '', turn_id: str = '', meta: str = '',
) -> None:
  sch = _schema()
  now = datetime.now(timezone.utc)
  conn = _connect()
  try:
    with conn.cursor() as cur:
      if title:
        cur.execute(
          f'''INSERT INTO {sch}.conversations (conversation_id, user_email, title, last_at)
              VALUES (%s, %s, %s, %s)
              ON CONFLICT (conversation_id)
              DO UPDATE SET last_at = EXCLUDED.last_at''',
          (conversation_id, user_email, title[:200], now),
        )
      else:
        cur.execute(
          f'UPDATE {sch}.conversations SET last_at = %s WHERE conversation_id = %s',
          (now, conversation_id),
        )
      cur.execute(
        f'''INSERT INTO {sch}.messages (id, conversation_id, user_email, role, content, turn_id, meta, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
        (str(uuid.uuid4()), conversation_id, user_email, role, content,
         turn_id or str(uuid.uuid4()), meta or '', now),
      )
    conn.commit()
  finally:
    conn.close()


async def list_conversations(*, user_email: str, limit: int = 50) -> list[dict]:
  sch = _schema()
  conn = _connect()
  try:
    with conn.cursor() as cur:
      cur.execute(
        f'''SELECT conversation_id, title, last_at FROM {sch}.conversations
            WHERE user_email = %s ORDER BY last_at DESC LIMIT %s''',
        (user_email, int(limit)),
      )
      rows = cur.fetchall()
  finally:
    conn.close()
  return [{'conversation_id': r[0], 'title': r[1], 'last_at': str(r[2])} for r in rows]


async def get_conversation(*, user_email: str, conversation_id: str) -> list[dict]:
  sch = _schema()
  conn = _connect()
  try:
    with conn.cursor() as cur:
      cur.execute(
        f'''SELECT role, content, turn_id, meta, created_at FROM {sch}.messages
            WHERE user_email = %s AND conversation_id = %s ORDER BY created_at ASC''',
        (user_email, conversation_id),
      )
      rows = cur.fetchall()
  finally:
    conn.close()
  return [
    {'role': r[0], 'content': r[1], 'turn_id': r[2], 'meta': r[3], 'created_at': str(r[4])}
    for r in rows
  ]
