"""
worker_watchdog.py — restart a Celery worker that has silently stopped consuming.

On 2026-08-12 the privacy / abdm / nhcx workers lost their Redis connection
("Connection to broker lost") and never reconnected. The worker process stayed
alive, so Docker never restarted it, and those workers processed nothing for
six weeks. A hung worker also stops answering ``celery inspect ping``.

The watchdog runs as a daemon thread in the worker's main process. Every
WORKER_WATCHDOG_INTERVAL seconds it pings its own node through the broker. After
WORKER_WATCHDOG_MAX_FAILURES misses in a row it exits the process, so the
container's restart policy (``restart: unless-stopped``) starts a fresh worker.

Settings (env vars):
    WORKER_WATCHDOG_ENABLED       default "true"
    WORKER_WATCHDOG_INTERVAL      seconds between pings, default 60
    WORKER_WATCHDOG_TIMEOUT       seconds to wait for the pong, default 10
    WORKER_WATCHDOG_MAX_FAILURES  misses in a row before exiting, default 5
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time

logger = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, default)))
    except ValueError:
        return default


def ping_ok(app, nodename: str, timeout: float) -> bool:
    """True if ``nodename`` answers a broadcast ping within ``timeout`` seconds."""
    try:
        replies = app.control.ping(destination=[nodename], timeout=timeout) or []
    except Exception as exc:
        logger.warning("worker watchdog: ping failed (%s)", type(exc).__name__)
        return False
    return any(nodename in reply for reply in replies)


def _exit_process() -> None:
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1)  # sys.exit() would only end this thread


def watch(app, nodename: str, interval: int, timeout: int, max_failures: int,
          sleep=time.sleep, exit_process=_exit_process) -> None:
    """Ping loop. Calls ``exit_process()`` after ``max_failures`` misses in a row."""
    failures = 0
    while True:
        sleep(interval)
        if ping_ok(app, nodename, timeout):
            if failures:
                logger.info("worker watchdog: %s is answering again", nodename)
            failures = 0
            continue

        failures += 1
        logger.warning(
            "worker watchdog: %s did not answer ping (%d/%d)",
            nodename, failures, max_failures,
        )
        if failures >= max_failures:
            logger.critical(
                "worker watchdog: %s stopped responding — exiting so the container restarts",
                nodename,
            )
            exit_process()
            return


def start_worker_watchdog(app, consumer) -> None:
    """Start the watchdog once per worker process. Call from ``worker_ready``."""
    global _started
    if os.getenv("WORKER_WATCHDOG_ENABLED", "true").strip().lower() in ("0", "false", "no", "off"):
        logger.info("worker watchdog disabled")
        return

    nodename = getattr(consumer, "hostname", None)
    if not nodename:
        logger.warning("worker watchdog: no worker node name — not started")
        return

    with _lock:
        if _started:
            return
        _started = True

    interval = _env_int("WORKER_WATCHDOG_INTERVAL", 60)
    timeout = _env_int("WORKER_WATCHDOG_TIMEOUT", 10)
    max_failures = _env_int("WORKER_WATCHDOG_MAX_FAILURES", 5)
    threading.Thread(
        target=watch,
        args=(app, nodename, interval, timeout, max_failures),
        name="worker-watchdog",
        daemon=True,
    ).start()
    logger.info(
        "worker watchdog started for %s (ping every %ds, exit after %d misses)",
        nodename, interval, max_failures,
    )
