import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

IMMICH_URL = os.getenv("IMMICH_URL", "http://localhost:2283").rstrip('/')
API_KEY = os.getenv("IMMICH_API_KEY", "")

try:
    CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "120"))
    if CHECK_INTERVAL < 10:
        logger.warning("CHECK_INTERVAL too low, setting to 10s.")
        CHECK_INTERVAL = 10
except ValueError:
    logger.error("CHECK_INTERVAL must be an integer, falling back to 120s.")
    CHECK_INTERVAL = 120

_monitored_jobs_env = os.getenv("MONITORED_JOBS", "faceDetection,smartSearch,metadataExtraction")
MONITORED_JOBS = [job.strip() for job in _monitored_jobs_env.split(",") if job.strip()]
