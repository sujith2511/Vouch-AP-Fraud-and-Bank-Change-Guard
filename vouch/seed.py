"""Load vendors and emails into the DB. Adapters accept our data/vendors.json + emails.jsonl schema and tolerate common
variants, so Xanath's seed format only needs a small tweak here (see _vendor_fields/_email_fields)."""
import json, statistics

from . import core


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
