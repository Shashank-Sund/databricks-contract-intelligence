"""Contract document search (RAG over the Vector Search index).

Used as the supervisor agent's `contract_search` tool for contract-document /
clause questions ("what does the contract allow", "compare timely-filing
windows", "which contracts renew soon").

Flow:
  1. Query the Databricks Vector Search index for the most relevant contract
     chunks (run with the caller's token, so UC permissions on the index apply).
  2. Ask the RAG generation model (Claude Opus) to synthesize a grounded answer
     that cites the source_file (and page) for each claim.

Returns the answer plus a citation list the UI can render.

The Vector Search query endpoint returns {manifest.columns, result.data_array}
for a query_text search; we normalize that into citation-bearing chunks.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config_loader import config_loader
from .model_client import complete

logger = logging.getLogger(__name__)


def _rag_config() -> dict:
  return config_loader.app_config.get('rag', {}) or {}


# Optional retrieval scoping. When a tool's config provides a `scope_filter`, a
# question that names exactly one "entity" is restricted to that entity's
# document set, so a question about one entity isn't answered with another's
# identically-titled section. Generic and config-driven; the healthcare example
# fills `entities` with payers and their contract files. Vector Search LIKE
# tokenizes on whitespace (filenames are a single token), so we filter on exact
# column-value IN-lists.
#
# scope_filter shape:
#   {"column": "source_file",
#    "entities": {"<Name>": {"aliases": ["..."], "values": ["file1", "file2"]}}}


def _scoped_values(question: str, scope_filter: dict | None) -> tuple[str, list[str]] | None:
  """If exactly one configured entity is named in the question, return
  (column, values) to filter on. None means search the whole corpus."""
  if not scope_filter:
    return None
  column = scope_filter.get('column')
  entities = scope_filter.get('entities') or {}
  if not column or not entities:
    return None
  q = question.lower()
  matched = [
    e.get('values') or []
    for e in entities.values()
    if any(a.lower() in q for a in (e.get('aliases') or []))
  ]
  return (column, matched[0]) if len(matched) == 1 and matched[0] else None


async def _vector_query(
  *, host: str, token: str, question: str, scope_filter: dict | None = None
) -> list[dict]:
  """Return the top document chunks for a question as list of dicts."""
  cfg = _rag_config()
  index = cfg.get('vector_search_index')
  if not index:
    raise RuntimeError('rag.vector_search_index is not configured.')
  columns = cfg.get('columns', ['chunk_id', 'source_file', 'page_id', 'text'])
  num_results = int(cfg.get('num_results', 5))
  url = f'{host.rstrip("/")}/api/2.0/vector-search/indexes/{index}/query'
  payload = {'query_text': question, 'columns': columns, 'num_results': num_results}
  scoped = _scoped_values(question, scope_filter)
  if scoped:
    # Scope to the named entity's documents so we quote ITS section, not another
    # document's identically-titled one.
    column, values = scoped
    payload['filters_json'] = json.dumps({column: values})
  async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10)) as client:
    resp = await client.post(
      url, headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
      json=payload,
    )
    if resp.status_code != 200:
      raise RuntimeError(f'vector search failed {resp.status_code}: {resp.text[:300]}')
    body = resp.json()
  manifest_cols = [c.get('name') for c in (body.get('manifest', {}).get('columns') or [])]
  rows = (body.get('result', {}) or {}).get('data_array') or []
  out = []
  for r in rows:
    rec = {manifest_cols[i]: r[i] for i in range(min(len(manifest_cols), len(r)))}
    out.append(rec)
  return out


def _format_context(chunks: list[dict]) -> str:
  parts = []
  for i, c in enumerate(chunks, 1):
    src = c.get('source_file', 'unknown')
    page = c.get('page_id', '')
    page_str = f', page {page}' if page not in ('', None) else ''
    parts.append(f'[Source {i}: {src}{page_str}]\n{c.get("text", "")}')
  return '\n\n---\n\n'.join(parts)


# Generic default. The domain version (e.g. the healthcare example's) is set via
# `rag.system_prompt` in the app config.
DEFAULT_DOC_SYSTEM = (
  'You are a document analyst. Answer the question using ONLY the excerpts '
  'provided. Quote the relevant language and ALWAYS cite the source file (and '
  'page when shown), e.g. "(filename, page 2)". If the excerpts do not contain '
  'the answer, say so plainly rather than guessing. Be concise and precise.'
)


async def search(
  *, host: str, token: str, question: str, scope_filter: dict | None = None
) -> dict[str, Any]:
  """Run document RAG. Returns {ok, answer, citations:[{source_file, page_id}], chunks}."""
  try:
    chunks = await _vector_query(
      host=host, token=token, question=question, scope_filter=scope_filter
    )
  except Exception as e:  # noqa: BLE001
    logger.exception('document search vector query failed')
    return {'ok': False, 'error': str(e), 'answer': '', 'citations': [], 'chunks': []}

  if not chunks:
    return {
      'ok': True,
      'answer': 'No relevant document text was found for that question.',
      'citations': [],
      'chunks': [],
    }

  context = _format_context(chunks)
  prompt = f'EXCERPTS:\n\n{context}\n\nQUESTION: {question}\n\nGrounded answer with citations:'
  system = _rag_config().get('system_prompt') or DEFAULT_DOC_SYSTEM
  endpoint = _rag_config().get('generation_endpoint', 'databricks-claude-opus-4-8')
  try:
    answer = await complete(
      host=host, token=token, endpoint=endpoint, system=system, prompt=prompt, max_tokens=2000
    )
  except Exception as e:  # noqa: BLE001
    logger.exception('contract_search generation failed')
    return {'ok': False, 'error': str(e), 'answer': '', 'citations': [], 'chunks': chunks}

  # Deduped citation list (source_file + page) in retrieval order.
  seen = set()
  citations = []
  for c in chunks:
    key = (c.get('source_file'), c.get('page_id'))
    if key in seen:
      continue
    seen.add(key)
    citations.append({'source_file': c.get('source_file'), 'page_id': c.get('page_id')})

  return {'ok': True, 'answer': answer.strip(), 'citations': citations, 'chunks': chunks}
