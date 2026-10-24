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


def test_dotfile_locking_for_azure_files(tmp_path, monkeypatch):
    """The settings used on the Azure Files mount: schema, a real transition, concurrent writers, audit chain."""
    import threading
    from vouch import core
    monkeypatch.setenv("VOUCH_SQLITE_VFS", "unix-dotfile")
    monkeypatch.setenv("VOUCH_SQLITE_JOURNAL", "DELETE")
    p = str(tmp_path / "share.db"); init_db(p).close()
    c = connect(p)
    c.execute("INSERT INTO vendors(vendor_id,name,domain,typical_amount) VALUES('V1','Acme','acme.example',100)")
    errors = []
    def ingest(n):
        try:
            k = connect(p)
            for j in range(5):
                core.ingest_item(k, item_id=f"I{n}-{j}", vendor_id="V1", email={"from": "a@acme.example"},
                                 claim={"invoice_number": f"N{n}{j}", "amount": 50.0})
        except Exception as e:
            errors.append(repr(e))
    ts = [threading.Thread(target=ingest, args=(n,)) for n in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert errors == [] and c.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 20
    assert core.verify_audit_chain(c) == (True, None)


def test_unknown_vfs_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("VOUCH_SQLITE_VFS", "unix-none")
    with pytest.raises(ValueError):
        connect(str(tmp_path / "d.db"))


def test_unknown_mode_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("VOUCH_SQLITE_JOURNAL", "OFF")       # OFF would disable rollback: never allowed
    with pytest.raises(ValueError):
        connect(str(tmp_path / "c.db"))
