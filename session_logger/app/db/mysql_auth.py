"""
mysql_auth.py — keep MySQL connections working across password rotations.

MYSQL_PASSWORD is resolved from Secret Manager once, at process start. When the
``mysql-password`` secret is rotated, pooled connections keep working, but every
*new* connection is rejected with MySQL error 1045 ("Access denied") until the
container restarts — so POST /log calls from the service workers fail and their
documents silently disappear from the dashboard counts.

``attach_password_refresh(engine)`` hooks SQLAlchemy's connect step: on error
1045 the latest password is re-fetched from Secret Manager and the connection is
retried once with it.
"""
import logging
import os

from sqlalchemy import event

from common.secrets import refresh_secret

logger = logging.getLogger(__name__)

MYSQL_ACCESS_DENIED = 1045


def connect_with_password_refresh(dialect, conn_rec, cargs, cparams):
    """SQLAlchemy ``do_connect`` handler. Connects with the current password and,
    if MySQL rejects it, retries once with the password re-fetched from Secret
    Manager."""
    cparams["password"] = os.environ.get("MYSQL_PASSWORD", cparams.get("password"))
    try:
        return dialect.dbapi.connect(*cargs, **cparams)
    except dialect.dbapi.OperationalError as exc:
        if not exc.args or exc.args[0] != MYSQL_ACCESS_DENIED:
            raise
        fresh = refresh_secret("MYSQL_PASSWORD")
        if not fresh or fresh == cparams["password"]:
            raise
        logger.warning(
            "MySQL rejected the cached password (error 1045) — retrying with the "
            "rotated password re-fetched from Secret Manager"
        )
        cparams["password"] = fresh
        return dialect.dbapi.connect(*cargs, **cparams)


def attach_password_refresh(engine):
    """Register ``connect_with_password_refresh`` on a MySQL engine."""
    event.listen(engine, "do_connect", connect_with_password_refresh)
    return engine
