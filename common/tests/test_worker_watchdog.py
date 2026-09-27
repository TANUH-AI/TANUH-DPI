"""
Tests for common/worker_watchdog.py — a Celery worker that stops answering
pings must exit so its container restarts (2026-08-12 hung-worker incident).

Run from the repo root:  python -m pytest common/tests
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from common import worker_watchdog as wd

NODE = "privacy-worker@abc123def456"


class StopLoop(Exception):
    pass


class FakeControl:
    """Replays a scripted list of ping outcomes: True = pong, False = no reply,
    Exception instance = raise."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def ping(self, destination, timeout):
        self.calls.append((tuple(destination), timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return [{NODE: {"ok": "pong"}}] if outcome else []


def _run(outcomes, max_failures=3):
    """Run watch() until it exits or the scripted outcomes run out."""
    app = SimpleNamespace(control=FakeControl(outcomes))
    exits = []

    def sleep(_seconds):
        if not app.control.outcomes:
            raise StopLoop

    def exit_process():
        exits.append(len(app.control.calls))

    try:
        wd.watch(app, NODE, interval=60, timeout=10, max_failures=max_failures,
                 sleep=sleep, exit_process=exit_process)
    except StopLoop:
        pass
    return app, exits


# ── watch loop ────────────────────────────────────────────────────────────────

def test_exits_after_consecutive_missed_pings():
    _, exits = _run([False, False, False])
    assert exits == [3]


def test_healthy_worker_never_exits():
    app, exits = _run([True] * 10)
    assert exits == []
    assert len(app.control.calls) == 10


def test_a_pong_resets_the_miss_counter():
    # two misses, a pong, then three misses → exits only on the 6th ping
    _, exits = _run([False, False, True, False, False, False])
    assert exits == [6]


def test_ping_errors_count_as_misses():
    _, exits = _run([ConnectionError("broker down")] * 3)
    assert exits == [3]


def test_pings_only_its_own_node_with_timeout():
    app, _ = _run([True])
    assert app.control.calls == [((NODE,), 10)]


def test_reply_from_another_node_is_a_miss():
    app = SimpleNamespace(control=SimpleNamespace(
        ping=lambda destination, timeout: [{"privacy-worker@other": {"ok": "pong"}}]
    ))
    assert wd.ping_ok(app, NODE, 10) is False


# ── start_worker_watchdog ─────────────────────────────────────────────────────

@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(wd, "_started", False)
    started = []

    class FakeThread:
        def __init__(self, target, args, name, daemon):
            started.append({"args": args, "name": name, "daemon": daemon})

        def start(self):
            pass

    monkeypatch.setattr(wd.threading, "Thread", FakeThread)
    return started


def test_starts_one_daemon_thread_per_process(fresh, monkeypatch):
    monkeypatch.delenv("WORKER_WATCHDOG_ENABLED", raising=False)
    app, consumer = object(), SimpleNamespace(hostname=NODE)

    wd.start_worker_watchdog(app, consumer)
    wd.start_worker_watchdog(app, consumer)

    assert len(fresh) == 1
    assert fresh[0]["daemon"] is True
    assert fresh[0]["args"] == (app, NODE, 60, 10, 5)


def test_settings_come_from_env(fresh, monkeypatch):
    monkeypatch.setenv("WORKER_WATCHDOG_INTERVAL", "30")
    monkeypatch.setenv("WORKER_WATCHDOG_TIMEOUT", "5")
    monkeypatch.setenv("WORKER_WATCHDOG_MAX_FAILURES", "4")
    wd.start_worker_watchdog("app", SimpleNamespace(hostname=NODE))
    assert fresh[0]["args"] == ("app", NODE, 30, 5, 4)


def test_can_be_disabled(fresh, monkeypatch):
    monkeypatch.setenv("WORKER_WATCHDOG_ENABLED", "false")
    wd.start_worker_watchdog("app", SimpleNamespace(hostname=NODE))
    assert fresh == []


def test_not_started_without_node_name(fresh, monkeypatch):
    monkeypatch.delenv("WORKER_WATCHDOG_ENABLED", raising=False)
    wd.start_worker_watchdog("app", SimpleNamespace(hostname=None))
    assert fresh == []


# ── wiring: every worker app starts the watchdog on worker_ready ─────────────

@pytest.mark.parametrize("module_name", [
    "common.celery_app",          # abdm + nhcx workers
    "privacy_filter.celery_app",
    "forgensic.celery_app",
])
def test_worker_apps_start_watchdog_on_ready(module_name, monkeypatch):
    for var in ("WORKER_METRICS_PORT", "PROMETHEUS_MULTIPROC_DIR"):
        monkeypatch.delenv(var, raising=False)
    module = importlib.import_module(module_name)
    calls = []
    monkeypatch.setattr(module, "start_worker_watchdog",
                        lambda app, consumer: calls.append((app, consumer)), raising=False)
    consumer = SimpleNamespace(hostname=NODE)

    module.on_worker_ready(sender=consumer)

    assert calls == [(module.celery_app, consumer)]
