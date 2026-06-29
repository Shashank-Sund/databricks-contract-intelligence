"""Health check endpoints."""

import logging
import time

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get('/health')
async def health_check(is_dev: bool = False):
  """Health check endpoint for monitoring app status.

  Returns application health status.
  """
  try:
    health_status = {
      'status': 'healthy',
      'timestamp': int(time.time() * 1000),
      'environment': 'development' if is_dev else 'production',
    }

    logger.info('Health check passed - all systems operational')
    return health_status

  except Exception as e:
    logger.error(f'Health check failed: {str(e)}')
    return {
      'status': 'unhealthy',
      'error': str(e),
      'timestamp': int(time.time() * 1000),
    }
