"""VOUCH_SQLITE_JOURNAL: WAL by default (local disk), DELETE for an Azure Files (SMB) mount."""
import pytest

from vouch.db import connect, init_db


def mode(path):
    return connect(path).execute("PRAGMA journal_mode").fetchone()[0]


def test_default_is_wal(tmp_path, monkeypatch):
    monkeypatch.delenv("VOUCH_SQLITE_JOURNAL", raising=False)
    p = str(tmp_path / "a.db"); init_db(p).close()
    assert mode(p) == "wal"


def test_delete_mode_for_network_shares(tmp_path, monkeypatch):
    monkeypatch.setenv("VOUCH_SQLITE_JOURNAL", "delete")
    p = str(tmp_path / "b.db"); init_db(p).close()
    assert mode(p) == "delete"


def test_unknown_mode_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("VOUCH_SQLITE_JOURNAL", "OFF")       # OFF would disable rollback: never allowed
    with pytest.raises(ValueError):
        connect(str(tmp_path / "c.db"))
