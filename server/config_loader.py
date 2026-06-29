"""Load app config from config/app.json.

In dev the file is re-read on every property access (so live edits show up
immediately); in production it is read once and memoized for the process
lifetime. Used by the /api/config/app endpoint and by anything else that
needs branding or agent config.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ConfigLoader:
  """Read config/app.json on demand (dev) or once at startup (prod)."""

  def __init__(self, config_dir: Path | None = None):
    self.config_dir = config_dir or Path(__file__).parent.parent / 'config'
    self._cached: Dict[str, Any] | None = None

  def _load(self) -> Dict[str, Any]:
    # APP_CONFIG_PATH lets a deployment point at a specific config file (e.g. an
    # instance config under examples/). A relative path is resolved against the
    # repo root so it works regardless of the process working directory. Falls
    # back to the repo's config/app.json if the override is missing.
    default_path = self.config_dir / 'app.json'
    override = os.environ.get('APP_CONFIG_PATH')
    path = default_path
    if override:
      p = Path(override)
      if not p.is_absolute():
        p = self.config_dir.parent / override  # repo root
      path = p if p.exists() else default_path
    if not path.exists():
      logger.warning(f'Config file not found: {path}')
      return {}
    try:
      with open(path) as f:
        return json.load(f)
    except json.JSONDecodeError as e:
      logger.error(f'Could not parse {path}: {e}')
      return {}

  @property
  def app_config(self) -> Dict[str, Any]:
    if os.environ.get('ENV', 'development') == 'development':
      return self._load()
    if self._cached is None:
      self._cached = self._load()
    return self._cached


config_loader = ConfigLoader()
