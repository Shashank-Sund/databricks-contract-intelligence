"""Supervisor agent: a generic, config-driven tool-calling router.

Runs an OpenAI-style tool-calling loop on the supervisor serving endpoint
(config: `supervisor.endpoint`). Its persona and tools come entirely from the
`agent` block of the app config, so the same code serves any domain. Two tool
backends are provided:

  * backend "genie"          -> a Genie space (governed natural-language SQL over
                                your tables). Returns a table + the SQL.
  * backend "vector_search"  -> grounded retrieval over a document corpus
                                (Vector Search index). Returns an answer + citations.

A config tool entry looks like:
  {"name": "...", "backend": "genie"|"vector_search", "description": "...",
   "question_description": "...",
   "space_id": "... optional, genie only - routes to a specific Genie space",
   "scope_filter": {... optional, vector_search}}

You can configure SEVERAL "genie" tools, each with its own "space_id" and a
description of what that space covers. The supervisor then routes a question to
the right space by its description. A genie tool without a "space_id" uses the
default space (genie.space_id / GENIE_SPACE_ID).

For compound questions the system prompt tells the model to call multiple tools
and combine the results. Genie tool calls run under the signed-in user's token
(OBO) so Unity Catalog masks apply, with a service-principal fallback.

If no `agent` block is configured, generic defaults below are used.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from ..config_loader import config_loader
from . import contract_search, genie_service
from .model_client import chat_completion

logger = logging.getLogger(__name__)

# Generic defaults, used only when the config has no `agent` block. Domain text
# (e.g. the healthcare example) lives in the config, never here.
DEFAULT_SYSTEM_PROMPT = (
  "You are a data assistant. Answer questions using the tools provided. Some "
  "tools query structured data (returning tables); others search documents "
  "(returning grounded text with citations). For a question that needs both, "
  "call the relevant tools and combine the results into one clear answer. Quote "
  "the citations returned by document tools and state numbers precisely. If a "
  "tool is not configured or returns an error, say so plainly and answer with "
  "whatever you do have."
)

DEFAULT_TOOLS = [
  {
    'name': 'query_data',
    'backend': 'genie',
    'description': (
      'Answer a quantitative/analytical question by running governed SQL over the '
      'configured data via a Genie space. Returns a table and the SQL.'
    ),
    'question_description': 'A clear, self-contained natural-language data question.',
  },
  {
    'name': 'search_documents',
    'backend': 'vector_search',
    'description': (
      'Answer a question from the document corpus using grounded retrieval. '
      'Returns an answer with source citations.'
    ),
    'question_description': 'A clear, self-contained natural-language question about the documents.',
  },
]


def _agent_cfg() -> dict:
  return config_loader.app_config.get('agent', {}) or {}


def _system_prompt() -> str:
  return _agent_cfg().get('system_prompt') or DEFAULT_SYSTEM_PROMPT


def _tool_specs() -> list[dict]:
  return _agent_cfg().get('tools') or DEFAULT_TOOLS


def _build_tools(specs: list[dict]) -> list[dict]:
  """Turn config tool specs into OpenAI-style function tool definitions."""
  tools = []
  for s in specs:
    tools.append({
      'type': 'function',
      'function': {
        'name': s['name'],
        'description': s.get('description', ''),
        'parameters': {
          'type': 'object',
          'properties': {
            'question': {
              'type': 'string',
              'description': s.get('question_description', 'A clear, self-contained question.'),
            }
          },
          'required': ['question'],
        },
      },
    })
  return tools


def _spec_for(name: str, specs: list[dict]) -> dict | None:
  for s in specs:
    if s.get('name') == name:
      return s
  return None


def _cfg() -> dict:
  return config_loader.app_config.get('supervisor', {}) or {}


def _sse_text(tool_result: dict) -> str:
  """Compact, model-facing serialization of a tool result (keeps token cost down)."""
  return json.dumps(tool_result)[:12000]


def _is_auth_error(err: str | None) -> bool:
  """True when a tool failed on an authorization/scope problem (so we can retry
  with the service-principal token)."""
  e = (err or '').lower()
  return any(s in e for s in ('403', '401', 'scope', 'permission', 'forbidden', 'unauthorized'))


async def _run_tool(
  name: str, args: dict, *, specs: list[dict], host: str, token: str,
  genie_host: str | None = None, genie_token: str | None = None,
  genie_fb_host: str | None = None, genie_fb_token: str | None = None,
) -> dict:
  question = args.get('question', '')
  spec = _spec_for(name, specs) or {}
  backend = spec.get('backend')

  if backend == 'genie':
    # Run Genie under the signed-in user's token (so Unity Catalog column masks
    # apply to THIS user); fall back to the service principal if the user token
    # lacks the Genie scope, so the agent never hard-fails.
    #
    # Multiple Genie spaces: a tool spec may carry its own "space_id" (alongside
    # its own name + description), so the supervisor can route across several
    # spaces by their descriptions. When a spec omits space_id, genie_service.ask
    # falls back to the default space (genie.space_id / GENIE_SPACE_ID).
    g_host = genie_host or host
    g_token = genie_token or token
    space_id = spec.get('space_id') or None
    res = await genie_service.ask(host=g_host, token=g_token, question=question, space_id=space_id)
    if not res.get('ok') and _is_auth_error(res.get('error')) and genie_fb_token:
      res = await genie_service.ask(
        host=genie_fb_host or host, token=genie_fb_token, question=question, space_id=space_id
      )
    # Trim rows for the model; the UI gets the full payload separately.
    model_view = {
      'ok': res.get('ok'),
      'text': res.get('text'),
      'sql': res.get('sql'),
      'columns': res.get('columns'),
      'rows': (res.get('rows') or [])[:30],
      'row_count': res.get('row_count'),
      'error': res.get('error'),
    }
    return {'model_view': model_view, 'ui': {'type': 'genie', **res}}

  if backend == 'vector_search':
    res = await contract_search.search(
      host=host, token=token, question=question, scope_filter=spec.get('scope_filter'),
    )
    model_view = {
      'ok': res.get('ok'),
      'answer': res.get('answer'),
      'citations': res.get('citations'),
      'error': res.get('error'),
    }
    return {'model_view': model_view, 'ui': {'type': 'contract', **res}}

  return {'model_view': {'ok': False, 'error': f'unknown tool/backend {name}'}, 'ui': None}


async def run(
  *, host: str, token: str, user_message: str, history: list[dict],
  genie_host: str | None = None, genie_token: str | None = None,
  genie_fb_host: str | None = None, genie_fb_token: str | None = None,
) -> AsyncIterator[dict]:
  """Drive the tool-calling loop. Yields events:
       {type:'tool_call', name, question}
       {type:'tool_result', name, ui}   # structured result for rich UI rendering
       {type:'answer', content}          # final assistant text
       {type:'error', message}
  """
  cfg = _cfg()
  endpoint = cfg.get('endpoint', 'databricks-claude-sonnet-4-6')
  max_tokens = int(cfg.get('max_tokens', 4000))
  max_iters = int(cfg.get('max_tool_iterations', 6))
  specs = _tool_specs()
  tools = _build_tools(specs)

  messages: list[dict] = [{'role': 'system', 'content': _system_prompt()}]
  for h in history:
    if h.get('role') in ('user', 'assistant') and (h.get('content') or '').strip():
      messages.append({'role': h['role'], 'content': h['content']})
  messages.append({'role': 'user', 'content': user_message})

  for _ in range(max_iters):
    try:
      msg = await chat_completion(
        host=host, token=token, endpoint=endpoint,
        messages=messages, tools=tools, max_tokens=max_tokens,
      )
    except Exception as e:  # noqa: BLE001
      logger.exception('supervisor model call failed')
      yield {'type': 'error', 'message': str(e)}
      return

    tool_calls = msg.get('tool_calls') or []
    if not tool_calls:
      yield {'type': 'answer', 'content': msg.get('content') or ''}
      return

    # Record the assistant turn that requested tools, then run them.
    messages.append({
      'role': 'assistant',
      'content': msg.get('content'),
      'tool_calls': tool_calls,
    })
    for tc in tool_calls:
      fn = tc.get('function', {}) or {}
      name = fn.get('name', '')
      try:
        args = json.loads(fn.get('arguments') or '{}')
      except json.JSONDecodeError:
        args = {}
      yield {'type': 'tool_call', 'name': name, 'question': args.get('question', '')}
      result = await _run_tool(
        name, args, specs=specs, host=host, token=token,
        genie_host=genie_host, genie_token=genie_token,
        genie_fb_host=genie_fb_host, genie_fb_token=genie_fb_token,
      )
      yield {'type': 'tool_result', 'name': name, 'ui': result['ui']}
      messages.append({
        'role': 'tool',
        'tool_call_id': tc.get('id'),
        'content': _sse_text(result['model_view']),
      })

  # Ran out of iterations: ask for a final answer with no more tools.
  try:
    msg = await chat_completion(
      host=host, token=token, endpoint=endpoint, messages=messages, max_tokens=max_tokens
    )
    yield {'type': 'answer', 'content': msg.get('content') or ''}
  except Exception as e:  # noqa: BLE001
    yield {'type': 'error', 'message': str(e)}
