"""Multi-model chat client.

Streams responses from ANY served model on Databricks (Claude, GPT, Gemini,
Llama, DBRX, ...) through the same code path. Every call hits a Databricks
serving endpoint, so if AI Gateway is enabled on that endpoint, the call is
automatically governed (logged, rate-limited, cost-tracked) no matter which
model the user picked.

Plain-English version:
- A "model" here is just a named serving endpoint in your workspace.
- The app reads the list of allowed models from config/app.json (the `models`
  list), so admins control which models users can pick, without code changes.
- We talk to every endpoint with the same OpenAI-compatible chat format, so
  adding a new model is just adding a line to the config.
"""

from __future__ import annotations

import json
import logging
import os
from typing import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

# Fallback model list if config/app.json doesn't define one. Each entry:
#   id:       value the UI sends back when the user picks this model
#   label:    what the user sees in the dropdown
#   endpoint: the Databricks serving endpoint name to call
# Confirm the exact endpoint names exist in YOUR workspace (Serving page).
DEFAULT_MODELS = [
  {'id': 'claude-sonnet', 'label': 'Claude Sonnet', 'endpoint': 'databricks-claude-sonnet-4'},
  {'id': 'claude-opus', 'label': 'Claude Opus', 'endpoint': 'databricks-claude-opus-4-1'},
  {'id': 'llama', 'label': 'Llama 3.3 70B', 'endpoint': 'databricks-meta-llama-3-3-70b-instruct'},
  # GPT and Gemini are reached via "external model" serving endpoints you create
  # in the workspace. Add them here once those endpoints exist, e.g.:
  # {'id': 'gpt', 'label': 'GPT', 'endpoint': 'azure-openai-gpt'},
  # {'id': 'gemini', 'label': 'Gemini', 'endpoint': 'google-gemini'},
]


def list_models(config: dict | None = None) -> list[dict]:
  """Return the models the UI should offer. Prefers config/app.json `models`."""
  if config and config.get('models'):
    return config['models']
  return DEFAULT_MODELS


def _endpoint_for(model_id: str, models: list[dict]) -> str:
  """Map a UI model id to its serving-endpoint name. Falls back to the first model."""
  for m in models:
    if m['id'] == model_id:
      return m['endpoint']
  return models[0]['endpoint'] if models else 'databricks-claude-sonnet-4'


async def stream_chat(
  *,
  host: str,
  token: str,
  endpoint: str,
  system: str,
  messages: list[dict[str, str]],
  max_tokens: int = 4000,
  temperature: float = 0.3,
) -> AsyncIterator[str]:
  """Stream a model's reply token-by-token from a Databricks serving endpoint.

  Works for any chat/foundation-model endpoint (Claude, GPT, Gemini, Llama, ...)
  because they all speak the OpenAI-compatible chat format. Yields each text
  chunk as it arrives. Raises RuntimeError on a non-200 response.
  """
  url = f'{host.rstrip("/")}/serving-endpoints/{endpoint}/invocations'
  full_messages = [{'role': 'system', 'content': system}, *messages] if system else messages
  # NOTE: we intentionally do not send `temperature`. Some models (e.g. GPT-5
  # reasoning models) only accept their default temperature and 400 otherwise.
  # Omitting it keeps one code path working across Claude/GPT/Gemini/Llama.
  payload = {
    'messages': full_messages,
    'max_tokens': max_tokens,
    'stream': True,
  }
  async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10)) as client:
    async with client.stream(
      'POST',
      url,
      headers={
        'Authorization': f'Bearer {token}',
        'Accept': 'text/event-stream',
        'Content-Type': 'application/json',
      },
      json=payload,
    ) as resp:
      if resp.status_code != 200:
        body = (await resp.aread()).decode('utf-8', errors='replace')
        raise RuntimeError(f'{endpoint} stream failed {resp.status_code}: {body[:500]}')
      async for line in resp.aiter_lines():
        if not line or not line.startswith('data:'):
          continue
        chunk_str = line[5:].strip()
        if not chunk_str or chunk_str == '[DONE]':
          continue
        try:
          chunk = json.loads(chunk_str)
        except json.JSONDecodeError:
          continue
        choices = chunk.get('choices') or []
        if not choices:
          continue
        delta = choices[0].get('delta') or {}
        token_text = delta.get('content')
        if token_text:
          yield token_text


async def chat_completion(
  *,
  host: str,
  token: str,
  endpoint: str,
  messages: list[dict],
  tools: list[dict] | None = None,
  max_tokens: int = 4000,
) -> dict:
  """Non-streaming OpenAI-style chat completion. Returns the raw `message` object
  (so callers can read `content` and `tool_calls`). Used by the supervisor's
  tool-calling loop. AI-Gateway-agnostic: just hits the serving endpoint."""
  url = f'{host.rstrip("/")}/serving-endpoints/{endpoint}/invocations'
  payload: dict = {'messages': messages, 'max_tokens': max_tokens}
  if tools:
    payload['tools'] = tools
  async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10)) as client:
    resp = await client.post(
      url,
      headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
      json=payload,
    )
    if resp.status_code != 200:
      raise RuntimeError(f'{endpoint} call failed {resp.status_code}: {resp.text[:400]}')
    data = resp.json()
    return data['choices'][0]['message']


async def complete(
  *, host: str, token: str, endpoint: str, system: str, prompt: str, max_tokens: int = 4000
) -> str:
  """Non-streaming convenience call. Returns the full text (used for file analysis)."""
  url = f'{host.rstrip("/")}/serving-endpoints/{endpoint}/invocations'
  msgs = [{'role': 'system', 'content': system}] if system else []
  msgs.append({'role': 'user', 'content': prompt})
  payload = {'messages': msgs, 'max_tokens': max_tokens}
  async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10)) as client:
    resp = await client.post(
      url,
      headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
      json=payload,
    )
    if resp.status_code != 200:
      raise RuntimeError(f'{endpoint} call failed {resp.status_code}: {resp.text[:400]}')
    return resp.json()['choices'][0]['message']['content']
