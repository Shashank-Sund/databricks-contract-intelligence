"""FastAPI entry point for Contract Intelligence.

Wires the API routers under /api and serves the React build (when present)
as static files at /. Run locally with `uvicorn server.app:app`; deployed by
app.yaml in Databricks Apps.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from .routers import chat, config as config_router, genie, health

logging.basicConfig(
  level=logging.INFO,
  format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)

env_local_loaded = load_dotenv(dotenv_path='.env.local')
env = os.getenv('ENV', 'development' if env_local_loaded else 'production')
logger.info(f'ENV={env} (env_local_loaded={env_local_loaded})')


@asynccontextmanager
async def lifespan(app: FastAPI):
  """FastAPI lifespan hook. The history table is created by scripts/setup.py,
  so startup just logs. Reserved for future startup work."""
  logger.info('Contract Intelligence starting up...')
  yield
  logger.info('Contract Intelligence shutting down.')


app = FastAPI(lifespan=lifespan, title='Contract Intelligence')

allowed_origins = ['http://localhost:3000'] if env == 'development' else []
app.add_middleware(
  CORSMiddleware,
  allow_origins=allowed_origins,
  allow_credentials=True,
  allow_methods=['*'],
  allow_headers=['*'],
)

API_PREFIX = '/api'
app.include_router(health.router, prefix=API_PREFIX, tags=['health'])
app.include_router(config_router.router, prefix=API_PREFIX, tags=['config'])
app.include_router(chat.router, prefix=API_PREFIX, tags=['chat'])
app.include_router(genie.router, prefix=API_PREFIX, tags=['genie'])

build_path = Path('.') / 'client/out'
if build_path.exists():
  logger.info(f'Serving static files from {build_path}')
  app.mount('/', StaticFiles(directory=str(build_path), html=True), name='static')
else:
  logger.warning(f'Build dir {build_path} not found.')
