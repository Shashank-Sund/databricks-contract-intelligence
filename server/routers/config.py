"""GET /api/config/app - returns a UI-safe view of config/app.json.

We intentionally do NOT return internal serving-endpoint names or persona
system prompts to the browser. The frontend only needs labels + ids to render
the model picker and persona dropdown; the backend maps ids -> endpoints and
ids -> system prompts server-side.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from ..config_loader import config_loader
from ..services.rbac_simple import get_principal

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get('/me')
async def me(request: Request) -> dict:
  """Return the logged-in user's identity (from the Apps SSO header in prod)."""
  p = get_principal(request)
  return {'email': p.email, 'is_steward': getattr(p, 'is_steward', False)}


@router.get('/config/app')
async def get_app_config(request: Request) -> dict:
  """Return UI-safe branding + home copy. Serving-endpoint names and the system
  prompt stay server-side."""
  cfg = config_loader.app_config
  return {
    'branding': cfg.get('branding', {}),
    'home': cfg.get('home', {}),
  }
