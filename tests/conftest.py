import json, pytest
from vouch import core
from vouch.db import init_db, connect

VENDORS = [
    {"vendor_id": "V1", "legal_name": "Acme Inc", "domain": "acme.example", "typical_amount": 1000.0, "phone": "(415) 555-0101",
     "bank": {"bank_name": "Old Bank", "routing": "999000001", "account": "TEST0000001"}, "split": "dev", "payments": [{"voucher": "P1", "amount": 1000.0, "fiscal_year": 2024}]},
    {"vendor_id": "V2", "legal_name": "Zed LLC", "domain": "zed.example", "typical_amount": 500.0, "phone": "(415) 555-0102",
     "bank": {"bank_name": "Old Bank", "routing": "999000002", "account": "TEST0000002"}, "split": "holdout", "payments": []},
]
OK_AUTH = {"spf": "pass", "dkim": "pass", "dmarc": "pass"}
NEW_BANK = {"bank_name": "New Bank", "routing": "999111111", "account": "TEST9999999"}


def make_email(vendor="acme.example", auth=None, reply_to=None, body="Please find invoice attached."):
    return {"from": f"Dana <dana@{vendor}>", "reply_to": reply_to or f"dana@{vendor}", "auth": auth or OK_AUTH, "subject": "Invoice", "body": body}


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "vouch.db")
    init_db(path).close()
    return path


@pytest.fixture
def db(db_path, tmp_path):
    conn = connect(db_path)
    from vouch.seed import load_vendors
    vp = tmp_path / "v.json"; vp.write_text(json.dumps(VENDORS)); load_vendors(conn, str(vp))
    return conn


@pytest.fixture
def mk(db):
    n = {"i": 0}
    def make(vendor_id="V1", amount=900.0, bank=None, email=None, invoice=None):
        n["i"] += 1
        return core.ingest_item(db, item_id=f"I{n['i']}", vendor_id=vendor_id, email=email or make_email(
            "acme.example" if vendor_id == "V1" else "zed.example"),
            claim={"invoice_number": invoice or f"INV-{n['i']}", "amount": amount, "currency": "USD", "claimed_bank": bank})
    return make
