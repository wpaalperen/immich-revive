#!/usr/bin/env python3
"""immich-revive — auto-retry failed immich ml jobs."""

import signal
import time
import logging
import sys

import requests

from config import IMMICH_URL, API_KEY, CHECK_INTERVAL, MONITORED_JOBS, SWEEP_EVERY

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
    return requests.put(f"{IMMICH_URL}{path}", json=body, headers=HEADERS, timeout=15)


def detect_api_version() -> str:
    """returns 'v2' if /api/queues is available, else 'v1'."""
    try:
        r = requests.get(f"{IMMICH_URL}/api/queues", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return "v2"
    except requests.exceptions.RequestException:
        pass
    return "v1"


def clear_failed(job_name: str) -> bool:
    """clear failed entries from bullmq. works on both v1 and v2 — the legacy
    endpoint is the only safe way because the v2 DELETE /api/queues/:name/jobs
    calls Queue.drain() which destroys ALL waiting jobs, not just failed ones."""
    r = _put(f"/api/jobs/{job_name}", {"command": "clear-failed"})
    if r.status_code not in (200, 201, 204):
        logger.error("[%s] clear-failed failed (HTTP %s): %s", job_name, r.status_code, r.text)
        return False
    return True


def start_queue(job_name: str) -> bool:
    """tell immich to scan db for unprocessed assets and queue them."""
    r = _put(f"/api/jobs/{job_name}", {"command": "start", "force": False})
    if r.status_code in (200, 201, 204):
        return True
    if r.status_code == 400:
        # queue already has active jobs — this is fine, means it's already processing
        return True
    logger.error("[%s] start failed (HTTP %s): %s", job_name, r.status_code, r.text)
    return False


# getting failed counts

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


# retry and sweep logic

def retry_failed(job_name: str) -> bool:
    """clear failed entries, then re-queue unprocessed assets."""
    if not clear_failed(job_name):
        return False
    return start_queue(job_name)


def sweep_unprocessed():
    """periodic full sweep: clear any lingering failed entries and trigger
    start to catch orphaned unprocessed assets in the database."""
    for job_name in MONITORED_JOBS:
        clear_failed(job_name)
        if start_queue(job_name):
            logger.info("[%s] sweep: triggered re-queue for unprocessed assets.", job_name)


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

            if retry_failed(job_name):
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
    logger.info("  sweep every    : %d cycles (~%d min)", SWEEP_EVERY, (SWEEP_EVERY * CHECK_INTERVAL) // 60)
    logger.info("  queues         : %s", ", ".join(MONITORED_JOBS))

    api_version = detect_api_version()
    if api_version == "v2":
        logger.info("  api            : v2 (/api/queues)")
    else:
        logger.info("  api            : v1 (/api/jobs)")

    logger.info("=" * 55)

    cycle = 0
    while running:
        cycle += 1

        check_and_resume(api_version)

        if cycle % SWEEP_EVERY == 0:
            try:
                sweep_unprocessed()
            except requests.exceptions.RequestException as e:
                logger.error("sweep failed: %s", e)

        for _ in range(CHECK_INTERVAL):
            if not running:
                break
            time.sleep(1)

    logger.info("stopped.")


if __name__ == "__main__":
    main()
