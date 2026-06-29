"""Per-user chat history, with a pluggable backend.

Two backends, selected by config (history.backend) or HISTORY_BACKEND env var:

  * "delta"    (default) - one row per message in a Delta table, via the SQL
                Statement Execution API. Zero new infra: needs only the SQL
                warehouse + Unity Catalog every workspace already has. This is
                what runs for the demo out of the box.

  * "lakebase" - managed Postgres (see lakebase_store.py). Activate by setting
                HISTORY_BACKEND=lakebase and providing LAKEBASE_PG_URL (or the
                instance via config + scripts/setup_lakebase.py). Same public
                API, so the rest of the app is unchanged.

A "conversation" is a group of message rows sharing a conversation_id, scoped
to the signed-in user_email so each person sees only their own chats.

All Delta reads/writes go through the SQL Statement Execution API with the
(host, token) resolved per request (the user's OBO token in prod), so history
respects the caller's identity.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config_loader import config_loader

logger = logging.getLogger(__name__)


def _backend() -> str:
  env = os.environ.get('HISTORY_BACKEND')
  if env:
    return env.lower()
  return (config_loader.app_config.get('history', {}) or {}).get('backend', 'delta').lower()


def _table() -> str:
  uc = config_loader.app_config.get('uc', {}) or {}
  cat = os.environ.get('CATALOG') or uc.get('catalog', 'contract_intelligence')
  sch = os.environ.get('SCHEMA') or uc.get('schema', 'contract_intelligence')
  tbl = os.environ.get('HISTORY_TABLE') or uc.get('history_table', 'chat_history')
  return f'{cat}.{sch}.{tbl}'


def _warehouse_id() -> str:
  wid = os.environ.get('WAREHOUSE_ID') or config_loader.app_config.get('warehouse_id')
  if not wid:
    raise RuntimeError('WAREHOUSE_ID is not set (env or config.warehouse_id).')
  return wid


async def _sql(host: str, token: str, statement: str, params: list[dict] | None = None) -> dict[str, Any]:
  url = f'{host.rstrip("/")}/api/2.0/sql/statements'
  payload: dict[str, Any] = {'statement': statement, 'warehouse_id': _warehouse_id(), 'wait_timeout': '30s'}
  if params:
    payload['parameters'] = params
  async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10)) as client:
    resp = await client.post(url, headers={'Authorization': f'Bearer {token}'}, json=payload)
    if resp.status_code != 200:
      raise RuntimeError(f'history SQL failed {resp.status_code}: {resp.text[:300]}')
    body = resp.json()
    state = (body.get('status') or {}).get('state')
    if state != 'SUCCEEDED':
      raise RuntimeError(f'history SQL state {state}: {(body.get("status") or {}).get("error")}')
    return body


def _rows(body: dict[str, Any]) -> list[list]:
  return body.get('result', {}).get('data_array') or []


# ---------------------------------------------------------------------------
# Public API (dispatches to the configured backend)
# ---------------------------------------------------------------------------

async def save_message(
  *, host: str, token: str, user_email: str, conversation_id: str,
  role: str, content: str, title: str = '', turn_id: str = '', meta: str = '',
) -> None:
  """Append one message row. Best-effort: a logging failure never breaks chat.

  meta is an optional JSON string for structured tool results (genie tables,
  contract citations) so a restored conversation can re-render them.
  """
  if _backend() == 'lakebase':
    try:
      from . import lakebase_store
      await lakebase_store.save_message(
        user_email=user_email, conversation_id=conversation_id, role=role,
        content=content, title=title, turn_id=turn_id, meta=meta,
      )
    except Exception as e:  # noqa: BLE001
      logger.warning(f'lakebase save_message failed (non-fatal): {e}')
    return
  try:
    await _sql(
      host, token,
      f'INSERT INTO {_table()} '
      '(id, user_email, conversation_id, title, role, content, turn_id, meta, created_at) '
      'VALUES (:id, :ue, :cid, :title, :role, :content, :turn_id, :meta, '
      'CAST(:ts AS TIMESTAMP))',
      [
        {'name': 'id', 'value': str(uuid.uuid4())},
        {'name': 'ue', 'value': user_email},
        {'name': 'cid', 'value': conversation_id},
        {'name': 'title', 'value': title[:200]},
        {'name': 'role', 'value': role},
        {'name': 'content', 'value': content},
        {'name': 'turn_id', 'value': turn_id or str(uuid.uuid4())},
        {'name': 'meta', 'value': meta or ''},
        {'name': 'ts', 'value': datetime.now(timezone.utc).isoformat()},
      ],
    )
  except Exception as e:  # noqa: BLE001
    logger.warning(f'save_message failed (non-fatal): {e}')


async def list_conversations(*, host: str, token: str, user_email: str, limit: int = 50) -> list[dict]:
  """Return the user's conversations (id + title + last activity), newest first."""
  if _backend() == 'lakebase':
    from . import lakebase_store
    return await lakebase_store.list_conversations(user_email=user_email, limit=limit)
  body = await _sql(
    host, token,
    f'SELECT conversation_id, MAX(title) AS title, MAX(created_at) AS last_at '
    f'FROM {_table()} WHERE user_email = :ue AND title <> "" '
    f'GROUP BY conversation_id ORDER BY last_at DESC LIMIT {int(limit)}',
    [{'name': 'ue', 'value': user_email}],
  )
  return [{'conversation_id': r[0], 'title': r[1], 'last_at': r[2]} for r in _rows(body)]


async def get_conversation(*, host: str, token: str, user_email: str, conversation_id: str) -> list[dict]:
  """Return all messages in one conversation (only if owned by this user)."""
  if _backend() == 'lakebase':
    from . import lakebase_store
    return await lakebase_store.get_conversation(user_email=user_email, conversation_id=conversation_id)
  body = await _sql(
    host, token,
    f'SELECT role, content, turn_id, meta, created_at FROM {_table()} '
    'WHERE user_email = :ue AND conversation_id = :cid ORDER BY created_at ASC',
    [{'name': 'ue', 'value': user_email}, {'name': 'cid', 'value': conversation_id}],
  )
  return [
    {'role': r[0], 'content': r[1], 'turn_id': r[2], 'meta': r[3], 'created_at': r[4]}
    for r in _rows(body)
  ]
