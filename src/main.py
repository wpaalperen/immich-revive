#!/usr/bin/env python3
"""immich-revive — auto-retry failed immich ml jobs."""

import signal
import time
import logging
import sys

import requests

from config import IMMICH_URL, API_KEY, CHECK_INTERVAL, MONITORED_JOBS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("immich-revive")

running = True


def _shutdown_handler(signum, frame):
    global running
    logger.info("shutdown signal received (signal %s), exiting...", signum)
    running = False


signal.signal(signal.SIGINT, _shutdown_handler)
signal.signal(signal.SIGTERM, _shutdown_handler)

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "x-api-key": API_KEY,
}


def _get(path: str):
    r = requests.get(f"{IMMICH_URL}{path}", headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def _put(path: str, body: dict):
    r = requests.put(f"{IMMICH_URL}{path}", json=body, headers=HEADERS, timeout=15)
    return r


def _delete(path: str, body: dict):
    r = requests.delete(f"{IMMICH_URL}{path}", json=body, headers=HEADERS, timeout=15)
    return r


def detect_api_version() -> str:
    """returns 'v2' if /api/queues is available, else 'v1'."""
    try:
        r = requests.get(f"{IMMICH_URL}/api/queues", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return "v2"
    except requests.exceptions.RequestException:
        pass
    return "v1"


# legacy api — immich < v2.4.0

def get_failed_counts_v1() -> dict[str, int]:
    data = _get("/api/jobs")
    result: dict[str, int] = {}
    for name in MONITORED_JOBS:
        info = data.get(name)
        if not info:
            continue
        failed = info.get("jobCounts", {}).get("failed", 0)
        if failed > 0:
            result[name] = failed
    return result


def retry_failed_v1(job_name: str) -> bool:
    # 1) clear failed entries from bullmq
    r = _put(f"/api/jobs/{job_name}", {"command": "clear-failed"})
    if r.status_code not in (200, 201, 204):
        logger.error("[%s] clear-failed failed (HTTP %s): %s", job_name, r.status_code, r.text)
        return False

    # 2) re-queue unprocessed assets
    r = _put(f"/api/jobs/{job_name}", {"command": "start", "force": False})
    if r.status_code not in (200, 201, 204):
        logger.error("[%s] start failed (HTTP %s): %s", job_name, r.status_code, r.text)
        return False

    return True


# new api — immich >= v2.4.0

def get_failed_counts_v2() -> dict[str, int]:
    queues = _get("/api/queues")
    result: dict[str, int] = {}
    for q in queues:
        name = q.get("name", "")
        if name not in MONITORED_JOBS:
            continue
        failed = q.get("statistics", {}).get("failed", 0)
        if failed > 0:
            result[name] = failed
    return result


def retry_failed_v2(job_name: str) -> bool:
    # 1) delete failed entries via new api
    r = _delete(f"/api/queues/{job_name}/jobs", {"failed": True})
    if r.status_code not in (200, 201, 204):
        logger.error("[%s] delete failed jobs failed (HTTP %s): %s", job_name, r.status_code, r.text)
        return False

    # 2) re-queue unprocessed assets
    r = _put(f"/api/jobs/{job_name}", {"command": "start", "force": False})
    if r.status_code not in (200, 201, 204):
        logger.error("[%s] start failed (HTTP %s): %s", job_name, r.status_code, r.text)
        return False

    return True


def check_and_resume(api_version: str):
    try:
        if api_version == "v2":
            failed = get_failed_counts_v2()
        else:
            failed = get_failed_counts_v1()

        if not failed:
            return

        for job_name, count in failed.items():
            logger.info("[%s] %d failed job(s) detected, clearing and re-queuing...", job_name, count)

            ok = (retry_failed_v2 if api_version == "v2" else retry_failed_v1)(job_name)
            if ok:
                logger.info("[%s] re-queued successfully.", job_name)
            else:
                logger.warning("[%s] retry failed, will try again next cycle.", job_name)

    except requests.exceptions.RequestException as e:
        logger.error("could not reach immich api: %s", e)


def main():
    if not API_KEY or API_KEY == "your_api_key_here":
        logger.error("IMMICH_API_KEY is not set. configure it in .env or as an environment variable.")
        sys.exit(1)

    logger.info("=" * 55)
    logger.info("  immich-revive")
    logger.info("=" * 55)
    logger.info("  server         : %s", IMMICH_URL)
    logger.info("  check interval : every %d seconds", CHECK_INTERVAL)
    logger.info("  queues         : %s", ", ".join(MONITORED_JOBS))

    api_version = detect_api_version()
    if api_version == "v2":
        logger.info("  api            : v2 (/api/queues)")
    else:
        logger.info("  api            : v1 (/api/jobs)")

    logger.info("=" * 55)

    while running:
        check_and_resume(api_version)
        for _ in range(CHECK_INTERVAL):
            if not running:
                break
            time.sleep(1)

    logger.info("stopped.")


if __name__ == "__main__":
    main()
