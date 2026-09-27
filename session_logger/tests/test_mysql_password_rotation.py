"""
Regression tests: the session-logger must keep writing to MySQL after the
database password secret is rotated.

The password is resolved from Secret Manager once, at process start. After a
rotation, every *new* MySQL connection was rejected with error 1045
("Access denied") until the container was restarted, so POST /log calls from
the service workers failed and their documents never reached the dashboard.

All credentials, projects and secret names below are placeholders.

Run from the repo root:  python -m pytest session_logger/tests
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event

from common import secrets
from session_logger.app.db import mysql_auth

STALE = "stale-placeholder"      # value before the rotation
ROTATED = "rotated-placeholder"  # value after the rotation
PROJECT = "test-project"
SM_ENTRY = "test-db-entry"


class FakeOperationalError(Exception):
    pass


def _fake_dialect(accepted: str, attempts: list[str], error_code: int = 1045):
    """A dialect whose DBAPI only accepts the ``accepted`` credential."""
    def connect(*_args, **kwargs):
        attempts.append(kwargs["password"])
        if kwargs["password"] != accepted:
            raise FakeOperationalError(error_code, "Access denied")
        return "connection"

    return SimpleNamespace(
        dbapi=SimpleNamespace(connect=connect, OperationalError=FakeOperationalError)
    )


def _cparams(value: str) -> dict:
    return {"password": value}


# ── do_connect hook ───────────────────────────────────────────────────────────

def test_rotated_password_is_refetched_and_connection_retried(monkeypatch):
    monkeypatch.setenv("MYSQL_PASSWORD", STALE)

    def fake_refresh(name):
        assert name == "MYSQL_PASSWORD"
        monkeypatch.setenv("MYSQL_PASSWORD", ROTATED)
        return ROTATED

    monkeypatch.setattr(mysql_auth, "refresh_secret", fake_refresh)
    attempts: list[str] = []

    conn = mysql_auth.connect_with_password_refresh(
        _fake_dialect(ROTATED, attempts), None, [], _cparams(STALE)
    )

    assert conn == "connection"
    assert attempts == [STALE, ROTATED]


def test_later_connections_use_the_refreshed_password(monkeypatch):
    # A previous connect already refreshed the env var.
    monkeypatch.setenv("MYSQL_PASSWORD", ROTATED)
    monkeypatch.setattr(mysql_auth, "refresh_secret", lambda name: pytest.fail("should not refetch"))
    attempts: list[str] = []

    mysql_auth.connect_with_password_refresh(
        _fake_dialect(ROTATED, attempts), None, [], _cparams(STALE)
    )

    assert attempts == [ROTATED]


def test_non_auth_errors_are_raised_without_refetching(monkeypatch):
    monkeypatch.setenv("MYSQL_PASSWORD", STALE)
    monkeypatch.setattr(mysql_auth, "refresh_secret", lambda name: pytest.fail("should not refetch"))

    with pytest.raises(FakeOperationalError):
        mysql_auth.connect_with_password_refresh(
            _fake_dialect(ROTATED, [], error_code=2003), None, [], _cparams(STALE)
        )


def test_access_denied_is_raised_when_secret_has_not_changed(monkeypatch):
    monkeypatch.setenv("MYSQL_PASSWORD", STALE)
    monkeypatch.setattr(mysql_auth, "refresh_secret", lambda name: STALE)
    attempts: list[str] = []

    with pytest.raises(FakeOperationalError):
        mysql_auth.connect_with_password_refresh(
            _fake_dialect(ROTATED, attempts), None, [], _cparams(STALE)
        )
    assert attempts == [STALE]


def test_access_denied_is_raised_when_secret_cannot_be_fetched(monkeypatch):
    monkeypatch.setenv("MYSQL_PASSWORD", STALE)
    monkeypatch.setattr(mysql_auth, "refresh_secret", lambda name: None)

    with pytest.raises(FakeOperationalError):
        mysql_auth.connect_with_password_refresh(
            _fake_dialect(ROTATED, []), None, [], _cparams(STALE)
        )


def test_attach_registers_hook_on_engine():
    engine = create_engine("mysql+pymysql://localhost/test_db")
    mysql_auth.attach_password_refresh(engine)
    assert event.contains(engine, "do_connect", mysql_auth.connect_with_password_refresh)


# ── common.secrets.refresh_secret ─────────────────────────────────────────────

def test_refresh_secret_fetches_latest_value_into_env(monkeypatch):
    monkeypatch.setenv("PROJECT_ID", PROJECT)
    monkeypatch.setenv("MYSQL_PASSWORD_SECRET", SM_ENTRY)
    monkeypatch.setenv("MYSQL_PASSWORD", STALE)
    monkeypatch.setattr(secrets, "_get_adc_token", lambda: "placeholder-adc")
    fetched = []

    def fake_access(project, name, adc):
        fetched.append((project, name))
        return ROTATED

    monkeypatch.setattr(secrets, "_access_secret", fake_access)

    assert secrets.refresh_secret("MYSQL_PASSWORD") == ROTATED
    assert fetched == [(PROJECT, SM_ENTRY)]
    assert secrets.os.environ["MYSQL_PASSWORD"] == ROTATED


def test_refresh_secret_without_pointer_returns_none(monkeypatch):
    monkeypatch.setenv("PROJECT_ID", PROJECT)
    monkeypatch.delenv("MYSQL_PASSWORD_SECRET", raising=False)
    monkeypatch.setattr(secrets, "_access_secret", lambda *a: pytest.fail("should not fetch"))

    assert secrets.refresh_secret("MYSQL_PASSWORD") is None


def test_refresh_secret_failure_keeps_old_value(monkeypatch):
    monkeypatch.setenv("PROJECT_ID", PROJECT)
    monkeypatch.setenv("MYSQL_PASSWORD_SECRET", SM_ENTRY)
    monkeypatch.setenv("MYSQL_PASSWORD", STALE)
    monkeypatch.setattr(secrets, "_get_adc_token", lambda: "placeholder-adc")

    def boom(*_args):
        raise OSError("secret manager unreachable")

    monkeypatch.setattr(secrets, "_access_secret", boom)

    assert secrets.refresh_secret("MYSQL_PASSWORD") is None
    assert secrets.os.environ["MYSQL_PASSWORD"] == STALE
