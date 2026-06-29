"""Genie Conversation API client.

Runs natural-language questions against a Genie space and returns the generated
SQL plus the tabular result. Used two ways:

  1. As the supervisor agent's genie tool(s) for quantitative/analytical
     questions. A tool may target a specific space via its configured space_id;
     otherwise the default space (genie.space_id / GENIE_SPACE_ID) is used.
  2. Directly from the "Genie spaces" side panel, where the user picks a space
     and queries it.

All calls run with whatever (host, token) the caller passes in. In production
that is the signed-in user's OBO token, so Genie executes the SQL under the
user's Unity Catalog permissions.

Validated flow against this workspace (2026-06-23):
  POST /api/2.0/genie/spaces/{space}/start-conversation  {"content": "..."}
    -> {conversation_id, message_id}
  GET  .../conversations/{cid}/messages/{mid}            (poll until COMPLETED)
    -> {status, attachments:[{query:{query, statement_id, ...}}, {text:{content}}]}
  GET  .../messages/{mid}/attachments/{att}/query-result
    -> {statement_response:{manifest.schema.columns, result.data_array}}
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from ..config_loader import config_loader

logger = logging.getLogger(__name__)


def genie_config() -> dict:
  return config_loader.app_config.get('genie', {}) or {}


def default_space_id() -> str | None:
  """Genie space id from env (per-deploy override) or config. None => not set."""
  return os.environ.get('GENIE_SPACE_ID') or genie_config().get('space_id') or None


def _headers(token: str) -> dict[str, str]:
  return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


async def list_spaces(*, host: str, token: str) -> list[dict]:
  """List Genie spaces the caller can access (id + title). User-permission scoped."""
  url = f'{host.rstrip("/")}/api/2.0/genie/spaces'
  async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10)) as client:
    resp = await client.get(url, headers=_headers(token))
    if resp.status_code != 200:
      raise RuntimeError(f'list genie spaces failed {resp.status_code}: {resp.text[:300]}')
    spaces = resp.json().get('spaces', []) or []
  return [
    {
      'space_id': s.get('space_id'),
      'title': s.get('title') or 'Untitled space',
      'description': (s.get('description') or '')[:240],
    }
    for s in spaces
    if s.get('space_id')
  ]


async def _query_result(
  *, host: str, token: str, space_id: str, conversation_id: str, message_id: str, attachment_id: str
) -> dict[str, Any]:
  url = (
    f'{host.rstrip("/")}/api/2.0/genie/spaces/{space_id}/conversations/'
    f'{conversation_id}/messages/{message_id}/attachments/{attachment_id}/query-result'
  )
  async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10)) as client:
    resp = await client.get(url, headers=_headers(token))
    if resp.status_code != 200:
      raise RuntimeError(f'genie query-result failed {resp.status_code}: {resp.text[:300]}')
    return resp.json()


def _shape_result(qr: dict[str, Any]) -> dict[str, Any]:
  """Normalize statement_response into {columns:[...], rows:[[...]], row_count}."""
  sr = qr.get('statement_response') or qr
  manifest = sr.get('manifest') or {}
  schema = manifest.get('schema') or {}
  columns = [c.get('name') for c in (schema.get('columns') or [])]
  data = (sr.get('result') or {}).get('data_array') or []
  return {'columns': columns, 'rows': data, 'row_count': len(data)}


async def ask(
  *, host: str, token: str, question: str, space_id: str | None = None,
  conversation_id: str | None = None
) -> dict[str, Any]:
  """Ask a Genie space one question. Returns:
       {ok, text, sql, columns, rows, row_count, space_id}
  or  {ok: False, error} when the space isn't configured or the call fails.
  """
  sid = space_id or default_space_id()
  if not sid:
    return {
      'ok': False,
      'error': 'Genie space not configured. Set GENIE_SPACE_ID (or genie.space_id in config).',
    }

  cfg = genie_config()
  poll_s = float(cfg.get('poll_seconds', 3))
  max_attempts = int(cfg.get('poll_max_attempts', 40))
  base = f'{host.rstrip("/")}/api/2.0/genie/spaces/{sid}'

  async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10)) as client:
    if conversation_id:
      # Follow-up turn: post into the existing conversation so Genie keeps the
      # prior turns as context (multi-turn / chain-of-thought).
      start = await client.post(
        f'{base}/conversations/{conversation_id}/messages',
        headers=_headers(token), json={'content': question},
      )
    else:
      start = await client.post(
        f'{base}/start-conversation', headers=_headers(token), json={'content': question}
      )
    if start.status_code != 200:
      return {'ok': False, 'error': f'Genie start failed {start.status_code}: {start.text[:300]}'}
    sj = start.json()
    cid = sj.get('conversation_id') or conversation_id
    mid = sj.get('message_id') or sj.get('id')
    if not cid or not mid:
      return {'ok': False, 'error': 'Genie did not return conversation/message ids.'}

    msg: dict[str, Any] = {}
    for _ in range(max_attempts):
      poll = await client.get(f'{base}/conversations/{cid}/messages/{mid}', headers=_headers(token))
      if poll.status_code != 200:
        return {'ok': False, 'error': f'Genie poll failed {poll.status_code}: {poll.text[:300]}'}
      # Genie embeds raw newlines in some fields; tolerate them.
      msg = poll.json()
      status = msg.get('status')
      if status == 'COMPLETED':
        break
      if status in ('FAILED', 'CANCELLED', 'QUERY_RESULT_EXPIRED'):
        return {'ok': False, 'error': f'Genie message status {status}.'}
      await asyncio.sleep(poll_s)
    else:
      return {'ok': False, 'error': 'Genie timed out before completing.'}

  # Pull the text answer + the query (SQL + result) out of attachments.
  text_answer = ''
  sql = ''
  result_shape = {'columns': [], 'rows': [], 'row_count': 0}
  query_att_id = None
  for att in msg.get('attachments', []) or []:
    if att.get('text') and not text_answer:
      text_answer = (att['text'].get('content') or '').strip()
    if att.get('query'):
      q = att['query']
      sql = (q.get('query') or q.get('statement') or '').strip()
      query_att_id = att.get('attachment_id')

  if query_att_id:
    try:
      qr = await _query_result(
        host=host, token=token, space_id=sid, conversation_id=cid,
        message_id=mid, attachment_id=query_att_id,
      )
      result_shape = _shape_result(qr)
    except Exception as e:  # noqa: BLE001
      logger.warning(f'genie query-result fetch failed: {e}')

  return {
    'ok': True,
    'text': text_answer,
    'sql': sql,
    'columns': result_shape['columns'],
    'rows': result_shape['rows'],
    'row_count': result_shape['row_count'],
    'space_id': sid,
    'conversation_id': cid,
  }
