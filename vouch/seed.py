"""Load vendors and emails into the DB. Adapters accept our data/vendors.json + emails.jsonl schema and tolerate common
variants, so Xanath's seed format only needs a small tweak here (see _vendor_fields/_email_fields)."""
import json, os, statistics

from . import core
from .db import open_sqlite


def _vendor_fields(v):
    pays = [p.get("amount") for p in v.get("payments", []) or v.get("payment_history", []) if (p.get("amount") or 0) > 0]
    typical = v.get("typical_amount") or (statistics.median(pays) if pays else 1000.0)
    bank = v.get("bank") or {}
    return {"vendor_id": v["vendor_id"], "name": v.get("legal_name") or v["name"], "domain": v["domain"], "typical_amount": float(typical),
            "bank_name": bank.get("bank_name") or "On-file bank", "bank_routing": str(bank.get("routing", "")), "bank_account": str(bank.get("account", "")),
            "phone": v.get("phone"), "split": v.get("split")}


def load_vendors(conn, path, with_history=True):
    vendors = json.load(open(path))
    if isinstance(vendors, dict) or any(v.get("demo_only") for v in vendors):
        raise ValueError("refusing to load demo-only real-company data (data/v2/demo_real_vendors.json) into the eval/seed DB")
    conn.execute("BEGIN IMMEDIATE")
    try:
        for v in vendors:
            f = _vendor_fields(v)
            conn.execute("INSERT OR IGNORE INTO vendors(vendor_id,name,domain,typical_amount,bank_name,bank_routing,bank_account,phone,split)"
                         " VALUES(:vendor_id,:name,:domain,:typical_amount,:bank_name,:bank_routing,:bank_account,:phone,:split)", f)
            if with_history:
                have = conn.execute("SELECT 1 FROM payment_history WHERE vendor_id=? LIMIT 1", (f["vendor_id"],)).fetchone()
                for p in ([] if have else v.get("payments", [])):
                    conn.execute("INSERT INTO payment_history(vendor_id,voucher,po,fiscal_year,po_date,amount,name_as_paid,department) VALUES(?,?,?,?,?,?,?,?)",
                                 (f["vendor_id"], p.get("voucher"), p.get("po"), p.get("fiscal_year"), p.get("po_date"), p.get("amount"),
                                  p.get("name_as_paid"), p.get("department")))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK"); raise
    return len(vendors)


def _email_fields(e):
    inv = e.get("invoice") or {}
    email = {k: e.get(k) for k in ("from", "reply_to", "auth", "subject", "body", "sender_domain_age_days", "sender_domain_age_simulated")}
    claim = {"invoice_number": inv.get("number"), "amount": inv.get("amount"), "currency": inv.get("currency", "USD"),
             "claimed_bank": e.get("claimed_bank")}
    return e["id"], e["vendor_id"], email, claim, e.get("truth"), e.get("split")


def ingest_emails(conn, path, limit=None):
    n = 0
    for line in open(path):
        if not line.strip():
            continue
        item_id, vendor_id, email, claim, truth, split = _email_fields(json.loads(line))
        core.ingest_item(conn, item_id=item_id, vendor_id=vendor_id, email=email, claim=claim, truth=truth, split=split)
        n += 1
        if limit and n >= limit:
            break
    return n


# ====================================================================== dataset v2 (data/v2/, see data/v2/DATASET_CARD.md)
import sqlite3
from pathlib import Path

UNKNOWN_VENDOR = "UNKNOWN"
V2 = {"vendors": "data/v2/vendors.v2.json", "payments": "data/v2/payments.v2.jsonl", "history": "data/v2/vendor_email_history.jsonl",
      "emails": "data/v2/emails.jsonl", "dev": "data/v2/emails.dev.jsonl", "holdout": "data/v2/emails.holdout.jsonl"}
PROFILE_DROP = {"voice", "lookalikes", "provenance", "line_items", "split", "invoice_number_style", "payments", "fx_rate_simulated", "industry_basis"}
# change types that would name the fraud scenario are coarsened: an extractor reading the email could not know them
COARSE_CHANGE = {"new_account": "new_account", "account_only": "account_only", "routing_only": "routing_only", "remit_address_only": "remit_address_only",
                 "assignment_of_receivables": "new_account", "new_vendor_setup": "new_account", "new_account_foreign": "new_account", None: None}


def dataset_version(explicit=None):
    return (explicit or os.environ.get("VOUCH_DATASET") or "v1").lower()


def evalkey_path(db_path):
    """Ground truth for evaluation lives in a SEPARATE file next to the DB; the API/agent code never opens it, only vouch.eval does."""
    return str(db_path) + ".evalkey"


def _v2_vendor_row(v):
    b = v.get("bank_on_file") or {}
    return {"vendor_id": v["vendor_id"], "name": v["legal_name"], "domain": v["domain"], "typical_amount": float(v.get("typical_amount") or 0),
            "bank_name": b.get("bank_name") or "", "bank_routing": str(b.get("routing_or_iban") or ""), "bank_account": str(b.get("account") or ""),
            "phone": v.get("phone_on_file"), "split": v.get("split")}


def _insert_vendor(conn, f):
    conn.execute("INSERT OR IGNORE INTO vendors(vendor_id,name,domain,typical_amount,bank_name,bank_routing,bank_account,phone,split)"
                 " VALUES(:vendor_id,:name,:domain,:typical_amount,:bank_name,:bank_routing,:bank_account,:phone,:split)", f)


def load_vendors_v2(conn, vendors_path=None, payments_path=None, history_path=None):
    """Registered vendors only (in_master). Phantom suppliers are NOT vendors: their emails load as items for the sentinel UNKNOWN vendor.
    payment_history.voucher holds the (simulated) INVOICE NUMBER so the policy's duplicate-invoice rule works on v2; the real SF voucher id stays in the data file."""
    vendors = json.load(open(vendors_path or V2["vendors"]))
    if isinstance(vendors, dict) or any(v.get("demo_only") for v in vendors):
        raise ValueError("refusing to load demo-only real-company data (data/v2/demo_real_vendors.json) into the eval/seed DB")
    reg = [v for v in vendors if v.get("in_master")]
    conn.execute("BEGIN IMMEDIATE")
    try:
        _insert_vendor(conn, {"vendor_id": UNKNOWN_VENDOR, "name": "Unknown supplier (not in vendor master)", "domain": "unknown.invalid", "typical_amount": 0.0,
                              "bank_name": "", "bank_routing": "", "bank_account": "", "phone": None, "split": None})
        for v in reg:
            _insert_vendor(conn, _v2_vendor_row(v))
            prof = {k: val for k, val in v.items() if k not in PROFILE_DROP}
            prof["invoice_number_pattern"] = (v.get("invoice_number_style") or {}).get("pattern")
            conn.execute("INSERT OR REPLACE INTO vendor_profile(vendor_id, profile) VALUES(?,?)", (v["vendor_id"], json.dumps(prof)))
        ids = {v["vendor_id"] for v in reg}
        for line in open(payments_path or V2["payments"]):
            if not line.strip(): continue
            p = json.loads(line)
            if p["vendor_id"] in ids:
                conn.execute("INSERT INTO payment_history(vendor_id,voucher,po,fiscal_year,po_date,amount,name_as_paid,department) VALUES(?,?,?,?,?,?,?,?)",
                             (p["vendor_id"], p["invoice_number"], p.get("po_number"), p["fiscal_year"], p.get("po_date"), p["amount"], p.get("name_as_paid"), p.get("department")))
        for line in open(history_path or V2["history"]):
            if not line.strip(): continue
            h = json.loads(line)
            keep = {k: h[k] for k in ("id", "vendor_id", "sent_at", "from_name", "from_addr", "channel", "tone", "kind", "subject", "body_text", "invoice", "claimed_bank", "device_footer", "mailer")}
            conn.execute("INSERT INTO email_history(id,vendor_id,sent_at,data) VALUES(?,?,?,?)", (h["id"], h["vendor_id"], h["sent_at"], json.dumps(keep)))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK"); raise
    return len(reg)


def _v2_item(e, registered):
    """Agent-facing views of a v2 email record. truth / provenance are NOT read here (see ingest_emails_v2)."""
    h = e["headers"]; cb = e.get("claimed_bank"); ct = COARSE_CHANGE.get(e.get("change_type"), "new_account")
    body = e["body_text"] + (("\n\n" + e["quoted_history"]) if e.get("quoted_history") else "")
    email = {"from": f"{e['from_name']} <{e['from_addr']}>", "reply_to": e["reply_to"], "to": e["to"], "cc": e["cc"], "auth": {"spf": h["spf"], "dkim": h["dkim"], "dmarc": h["dmarc"]},
             "subject": e["subject"], "body": body, "sent_at": e["sent_at"], "received_at": e["received_at"], "thread_id": e["thread_id"], "in_reply_to": e["in_reply_to"],
             "headers": {"return_path": h["return_path"], "message_id_domain": h["message_id_domain"], "mailer": h["mailer"], "received_hops": h["received_hops"], "origin_ip": h["origin_ip"]},
             "sender_domain_age_days": e["sender_domain_age_days"], "sender_domain_age_simulated": True, "language": e["language"],
             "attachments": [{"filename": a["filename"], "type": a["type"], "extracted_text": a["extracted_text"], "metadata": a["metadata"]} for a in e["attachments"]],
             "vendor_context": e["vendor_snapshot"]}
    if not registered:
        email["vendor_context"] = {"in_vendor_master": False, "note": "sender is not in the vendor master"}
    inv = e["invoice"]
    bank = None
    if cb:
        bank = {"bank_name": cb["bank_name"], "routing": cb["routing_or_iban"], "account": cb["account"], "country": cb["country"], "swift": cb.get("swift")}
        if e.get("change_type") == "account_only": bank["routing"] = None     # the message only states what it states
        if e.get("change_type") == "routing_only": bank["account"] = None
    claim = {"invoice_number": inv["number"], "amount": inv["amount"], "currency": inv["currency"], "po": inv["po"], "invoice_date": inv["date"], "due_date": inv["due_date"],
             "line_items": inv["line_items"], "claimed_bank": bank, "change_type": ct}
    return email, claim


def ingest_emails_v2(conn, db_path, which="emails", limit=None, emails_path=None):
    """Ingest v2 emails as items (actor sync). Ground truth goes to the separate evalkey file, never into the DB."""
    path = emails_path or V2[which]
    registered = {r["vendor_id"] for r in conn.execute("SELECT vendor_id FROM vendors")} - {UNKNOWN_VENDOR}
    key = open_sqlite(evalkey_path(db_path))   # honours VOUCH_SQLITE_VFS on the Azure Files mount
    key.execute("CREATE TABLE IF NOT EXISTS truth (item_id TEXT PRIMARY KEY, split TEXT, truth TEXT NOT NULL)")
    n = 0
    for line in open(path):
        if not line.strip(): continue
        e = json.loads(line)
        is_reg = e["vendor_id"] in registered
        email, claim = _v2_item(e, is_reg)
        core.ingest_item(conn, item_id=e["id"], vendor_id=e["vendor_id"] if is_reg else UNKNOWN_VENDOR, email=email, claim=claim, truth=None)
        key.execute("INSERT OR REPLACE INTO truth(item_id, split, truth) VALUES(?,?,?)", (e["id"], e["split"], json.dumps({**e["truth"], "vendor_id": e["vendor_id"]})))
        n += 1
        if limit and n >= limit: break
    key.commit(); key.close()
    return n


def seed_v2(conn, db_path, which="emails", limit=None):
    load_vendors_v2(conn)
    return ingest_emails_v2(conn, db_path, which, limit)


def main():
    import argparse
    from .db import connect, init_db
    ap = argparse.ArgumentParser(description="Seed a DB: python -m vouch.seed --db vouch.db [--dataset v2] [--which emails|dev|holdout]")
    ap.add_argument("--db", default="vouch.db"); ap.add_argument("--dataset", default=None); ap.add_argument("--which", default="emails", choices=["emails", "dev", "holdout"])
    a = ap.parse_args(); init_db(a.db).close(); c = connect(a.db)
    if dataset_version(a.dataset) == "v2":
        print("v2:", seed_v2(c, a.db, a.which), "emails loaded; truth in", evalkey_path(a.db))
    else:
        load_vendors(c, "data/vendors.json"); print("v1:", ingest_emails(c, "data/fixtures/emails_fixture.jsonl"), "emails loaded")


if __name__ == "__main__":
    main()
