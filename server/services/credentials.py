"""Resolve Databricks credentials per request.

In production (Databricks Apps), the app runs as its own service principal.
DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET are auto-injected, the SDK
picks them up via the default auth chain, and we exchange them for a short-
lived OAuth bearer token via ws.config.authenticate() on every request.

The bearer token has a ~1 hour TTL. The SDK caches it internally and refreshes
when it's close to expiry, but only when authenticate() is called, so we must
NOT cache the (host, token) tuple at the call site or we'll hand out stale
tokens. We DO hold a process-lifetime WorkspaceClient because it's an expensive
object to construct.

In dev, we skip OAuth entirely and use the PAT from .env.local.

User identity comes from the x-forwarded-email header in production and is
resolved separately by rbac_simple.get_principal. Credentials and identity
are intentionally decoupled so a steward can't accidentally act with a user's
auth.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from fastapi import HTTPException, Request

from ..config_loader import config_loader

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Creds:
  host: str
  token: str
  is_user_token: bool = False  # True when this token is the signed-in user's (OBO)


def _is_production() -> bool:
  return os.environ.get('ENV', 'development') == 'production'


def auth_mode() -> str:
  """How the app authenticates to Databricks for user-scoped calls (Genie, etc.):

    * "obo" (default)            - prefer the signed-in user's on-behalf-of token
                                   so Unity Catalog permissions/masks apply to THAT
                                   user, with a service-principal fallback when the
                                   user token isn't present or lacks the scope.
    * "service_principal"        - always use the app's service-principal token.
                                   Simpler to set up (no per-user UC grants), but
                                   every user sees the same SP-scoped view.

  Read from the AUTH_MODE env var (set in app.yaml) first, then `auth_mode` in the
  app config, defaulting to "obo".
  """
  env = os.environ.get('AUTH_MODE')
  if env:
    return env.strip().lower()
  cfg = config_loader.app_config.get('auth_mode')
  return (cfg or 'obo').strip().lower()


def _user_token(request: Request) -> str | None:
  """The signed-in user's OAuth token, forwarded by Databricks Apps when user
  authorization (OBO) is enabled on the app. None when not enabled."""
  return request.headers.get('x-forwarded-access-token') or request.headers.get(
    'X-Forwarded-Access-Token'
  )


# Module-level WorkspaceClient. The SDK caches OAuth tokens internally and
# refreshes them when they expire, so we hold one WorkspaceClient for the
# process lifetime and call authenticate() per request. Never assign a
# (host, token) tuple here. That snapshot would go stale at the 1h TTL.
_workspace_client = None


def _get_sp_credentials() -> tuple[str, str]:
  """Resolve host + a fresh bearer token via the SP M2M OAuth flow.

  Inside Databricks Apps, DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET
  are auto-injected, and WorkspaceClient() picks them up. We call
  authenticate() each request so an expired short-lived token gets
  auto-refreshed by the SDK.
  """
  global _workspace_client
  from databricks.sdk import WorkspaceClient

  if _workspace_client is None:
    _workspace_client = WorkspaceClient()
  ws = _workspace_client

  host = (ws.config.host or '').rstrip('/')
  auth_headers = ws.config.authenticate()
  bearer = auth_headers.get('Authorization', '')
  token = bearer.replace('Bearer ', '').strip()

  if not host or not token:
    raise RuntimeError(
      f'Could not get SP credentials: host={bool(host)}, token={bool(token)}'
    )
  return host, token


def get_creds(request: Request, prefer_user: bool = False) -> Creds:
  """Return fresh (host, token) for this request. Call once per route handler.

  OBO: when AUTH_MODE is "obo" (default), prefer_user is True, and Databricks Apps
  forwarded the signed-in user's token (x-forwarded-access-token), we run AS THE
  USER so Unity Catalog permissions apply (e.g. not everyone can see the data).
  When the user token isn't present (user authorization not enabled), we fall back
  to the app's service-principal token.

  When AUTH_MODE is "service_principal", prefer_user is ignored and the app always
  uses its service-principal token (see auth_mode()).
  """
  use_user = prefer_user and auth_mode() != 'service_principal'
  if _is_production():
    host = os.environ.get('DATABRICKS_HOST', '').rstrip('/')
    if use_user:
      ut = _user_token(request)
      if ut:
        if not host:
          # Resolve host from the SP client if not set via env.
          host, _ = _get_sp_credentials()
        return Creds(host=host, token=ut, is_user_token=True)
    try:
      sp_host, token = _get_sp_credentials()
      return Creds(host=host or sp_host, token=token)
    except Exception as e:
      logger.exception('Failed to resolve SP credentials')
      raise HTTPException(500, f'Auth resolution failed: {e}')

  # Dev mode: PAT from .env.local (acts as "the user" locally).
  host = os.environ.get('DATABRICKS_HOST', '').rstrip('/')
  if not host:
    raise HTTPException(500, 'DATABRICKS_HOST is not configured (dev).')
  token = os.environ.get('DATABRICKS_TOKEN', '')
  if not token:
    raise HTTPException(500, 'DATABRICKS_TOKEN is not configured (dev).')
  return Creds(host=host, token=token, is_user_token=True)
