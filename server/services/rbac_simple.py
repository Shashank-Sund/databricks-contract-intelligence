"""App-level identity and authorization.

Reads the caller's email from x-forwarded-email (set by Databricks Apps in
production) or falls back to env vars in dev. The "steward" role is a flat
allowlist of emails in STEWARD_EMAILS; stewards can see and delete other
users' reviews, regular users only see their own. Kept deliberately simple,
no DB-backed RBAC.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from fastapi import Request


@dataclass(frozen=True)
class Principal:
  email: str
  is_steward: bool


def get_principal(request: Request) -> Principal:
  """Resolve the current user from forwarded headers, fallback to env."""
  email = (
    request.headers.get('x-forwarded-email')
    or request.headers.get('X-Forwarded-Email')
    or os.environ.get('LOCAL_DEV_USER_EMAIL')
    or os.environ.get('DATABRICKS_USER_EMAIL')
    or 'anonymous@unknown'
  )
  steward_emails = {
    e.strip().lower()
    for e in os.environ.get('STEWARD_EMAILS', '').split(',')
    if e.strip()
  }
  return Principal(email=email, is_steward=email.lower() in steward_emails)
