"""Genie endpoints for the side panel.

  GET  /api/genie/spaces           - list spaces the signed-in user can access
  POST /api/genie/query            - query a chosen space directly

Both run with the caller's OBO token, so the space list and the SQL execution
respect the user's Unity Catalog / Genie permissions. The spaces list is cached
per-user for a short TTL to keep the panel snappy.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..services import genie_service
from ..services.credentials import get_creds
from ..services.rbac_simple import get_principal

logger = logging.getLogger(__name__)
router = APIRouter()

# Per-user cache of (timestamp, spaces). User-scoped because access varies.
_SPACES_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL_S = 300.0


class GenieQuery(BaseModel):
  question: str = Field(min_length=1)
  space_id: str | None = None
  conversation_id: str | None = None


@router.get('/genie/spaces')
async def list_genie_spaces(request: Request):
  """List Genie spaces the signed-in user can access (cached per user)."""
  principal = get_principal(request)
  creds = get_creds(request)
  now = time.time()
  hit = _SPACES_CACHE.get(principal.email)
  if hit and now - hit[0] < _CACHE_TTL_S:
    return {'spaces': hit[1], 'default_space_id': genie_service.default_space_id()}
  try:
    spaces = await genie_service.list_spaces(host=creds.host, token=creds.token)
  except Exception as e:  # noqa: BLE001
    logger.warning(f'list genie spaces failed: {e}')
    spaces = []
  _SPACES_CACHE[principal.email] = (now, spaces)
  return {'spaces': spaces, 'default_space_id': genie_service.default_space_id()}


def _is_auth_error(err: str | None) -> bool:
  e = (err or '').lower()
  return any(s in e for s in ('403', '401', 'scope', 'permission', 'forbidden', 'unauthorized'))


@router.post('/genie/query')
async def genie_query(request: Request, body: GenieQuery):
  """Query a chosen Genie space directly (separate from the supervisor chat).

  Runs under the signed-in user's OBO token so Unity Catalog column masks apply
  to THIS user; falls back to the service principal if the user token lacks the
  Genie scope, so the panel never hard-fails."""
  user_creds = get_creds(request, prefer_user=True)
  result = await genie_service.ask(
    host=user_creds.host, token=user_creds.token, question=body.question,
    space_id=body.space_id, conversation_id=body.conversation_id,
  )
  if not result.get('ok') and _is_auth_error(result.get('error')):
    sp = get_creds(request)
    result = await genie_service.ask(
      host=sp.host, token=sp.token, question=body.question,
      space_id=body.space_id, conversation_id=body.conversation_id,
    )
  return result
