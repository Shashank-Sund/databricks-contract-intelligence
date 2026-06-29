"""POST /api/chat - run the supervisor agent and stream its trace + answer.

The client sends the new message plus the visible conversation. We run the
supervisor tool-calling loop (Sonnet + the genie_query / contract_search tools),
streaming SSE events as it goes:

    {type:'meta', conversation_id}
    {type:'tool_call', name, question}        # "calling Genie / contract search"
    {type:'tool_result', name, ui}            # structured result for rich rendering
    {type:'token', delta}                      # final answer, streamed in chunks
    {type:'done', conversation_id}

Both the user message and the assistant reply (with a JSON `meta` blob holding
any tool UI payloads) are persisted to per-user history so a refresh restores
the conversation, tables and citations included.

Tool calls run with the caller's credentials (the signed-in user's OBO token in
production), so Genie/SQL/Vector Search execute under the user's UC permissions.
Nothing here depends on AI Gateway; if it's enabled on the endpoints, calls are
governed automatically.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services import history_store, supervisor
from ..services.credentials import get_creds
from ..services.rbac_simple import get_principal

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_HISTORY_TURNS = 12


class ChatTurn(BaseModel):
  role: str
  content: str


class ChatRequest(BaseModel):
  message: str = Field(min_length=1)
  conversation_id: str | None = None
  history: list[ChatTurn] = Field(default_factory=list)


def _sse(obj: dict) -> bytes:
  return f'data: {json.dumps(obj)}\n\n'.encode('utf-8')


@router.post('/chat')
async def chat(request: Request, body: ChatRequest):
  """Run the supervisor agent for one turn and stream the trace + answer."""
  principal = get_principal(request)
  creds = get_creds(request)  # service-principal token: model calls, contract search, history
  user_creds = get_creds(request, prefer_user=True)  # signed-in user (OBO) for Genie -> UC masks apply

  conversation_id = body.conversation_id or str(uuid.uuid4())
  is_new = body.conversation_id is None
  title = body.message.strip()[:60] if is_new else ''
  turn_id = str(uuid.uuid4())

  history = [
    {'role': t.role, 'content': t.content}
    for t in body.history[-MAX_HISTORY_TURNS:]
    if t.role in ('user', 'assistant') and t.content and t.content.strip()
  ]

  async def stream() -> AsyncIterator[bytes]:
    yield _sse({'type': 'meta', 'conversation_id': conversation_id})
    answer_parts: list[str] = []
    tool_uis: list[dict] = []
    errored = False
    try:
      async for evt in supervisor.run(
        host=creds.host, token=creds.token,
        genie_host=user_creds.host, genie_token=user_creds.token,
        genie_fb_host=creds.host, genie_fb_token=creds.token,
        user_message=body.message, history=history,
      ):
        et = evt.get('type')
        if et == 'tool_call':
          yield _sse({'type': 'tool_call', 'name': evt['name'], 'question': evt.get('question', '')})
        elif et == 'tool_result':
          if evt.get('ui'):
            tool_uis.append(evt['ui'])
          yield _sse({'type': 'tool_result', 'name': evt['name'], 'ui': evt.get('ui')})
        elif et == 'answer':
          text = evt.get('content') or ''
          answer_parts.append(text)
          # Stream the final answer in modest chunks so it feels live.
          for i in range(0, len(text), 24):
            yield _sse({'type': 'token', 'delta': text[i:i + 24]})
        elif et == 'error':
          errored = True
          yield _sse({'type': 'error', 'message': evt.get('message', 'agent error')})
    except Exception as e:  # noqa: BLE001
      logger.exception('supervisor stream failed')
      yield _sse({'type': 'error', 'message': str(e)})
      errored = True

    reply = ''.join(answer_parts)
    if not errored:
      meta = json.dumps({'tools': tool_uis}) if tool_uis else ''
      await history_store.save_message(
        host=creds.host, token=creds.token, user_email=principal.email,
        conversation_id=conversation_id, role='user', content=body.message,
        title=title, turn_id=turn_id,
      )
      await history_store.save_message(
        host=creds.host, token=creds.token, user_email=principal.email,
        conversation_id=conversation_id, role='assistant', content=reply,
        turn_id=turn_id, meta=meta,
      )
    yield _sse({'type': 'done', 'conversation_id': conversation_id})

  return StreamingResponse(
    stream(),
    media_type='text/event-stream',
    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
  )


@router.get('/conversations')
async def conversations(request: Request):
  """List the current user's saved conversations (newest first)."""
  principal = get_principal(request)
  creds = get_creds(request)
  try:
    items = await history_store.list_conversations(
      host=creds.host, token=creds.token, user_email=principal.email
    )
  except Exception as e:  # noqa: BLE001
    logger.warning(f'list_conversations failed: {e}')
    items = []
  return {'conversations': items}


@router.get('/conversations/{conversation_id}')
async def conversation_detail(request: Request, conversation_id: str):
  """Return all messages in one of the current user's conversations."""
  principal = get_principal(request)
  creds = get_creds(request)
  try:
    msgs = await history_store.get_conversation(
      host=creds.host, token=creds.token,
      user_email=principal.email, conversation_id=conversation_id,
    )
  except Exception as e:  # noqa: BLE001
    logger.warning(f'get_conversation failed: {e}')
    msgs = []
  return {'conversation_id': conversation_id, 'messages': msgs}
