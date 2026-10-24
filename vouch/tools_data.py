"""Read-only data access for the agent's tools (Sujith defines the tool signatures; these are the implementations).
None of these can change state."""
import json, re
from . import core

def _lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]

def read_vendor_history(conn, vendor_id, limit=50):
    rows = conn.execute("SELECT voucher,po,fiscal_year,po_date,amount,name_as_paid,department FROM payment_history WHERE vendor_id=? "
                        "ORDER BY fiscal_year DESC, id DESC LIMIT ?", (vendor_id, limit)).fetchall()
    v = core._vendor(conn, vendor_id)
    out = {"vendor": {k: v[k] for k in ("vendor_id", "name", "domain", "typical_amount", "phone")} if v else None,
           "bank_on_file": core._mask(v["bank"]) if v else None, "payments": [dict(r) for r in rows]}
    prof = conn.execute("SELECT profile FROM vendor_profile WHERE vendor_id=?", (vendor_id,)).fetchone()
    if prof:
        out["profile"] = _mask_profile(json.loads(prof["profile"]))
    return out


def _mask_profile(p):
    """Vendor profile as the agent may see it: account numbers masked to the last 4 digits."""
    def m(b): return {**b, "account": "*" * max(0, len(str(b.get("account") or "")) - 4) + str(b.get("account") or "")[-4:], "routing_or_iban": b.get("routing_or_iban")} if b else b
    p = dict(p)
    p["bank_on_file"] = m(p.get("bank_on_file"))
    p["bank_change_history"] = [{**h, "from": m(h.get("from")), "to": m(h.get("to"))} for h in p.get("bank_change_history", [])]
    return p


def read_email_history(conn, vendor_id, limit=25):
    """Past legitimate emails from this vendor (baseline for tone, signature, mailer, timing)."""
    rows = conn.execute("SELECT data FROM email_history WHERE vendor_id=? ORDER BY sent_at DESC LIMIT ?", (vendor_id, limit)).fetchall()
    return {"vendor_id": vendor_id, "emails": [json.loads(r["data"]) for r in rows]}

def compare_amounts(conn, vendor_id, amount):
    v = core._vendor(conn, vendor_id)
    pos = sorted(r["amount"] for r in conn.execute("SELECT amount FROM payment_history WHERE vendor_id=? AND amount>0", (vendor_id,)))
    ratio = amount / v["typical_amount"] if v and v["typical_amount"] else None
    pct = (sum(1 for a in pos if a <= amount) / len(pos)) if pos else None
    return {"amount": amount, "typical": v["typical_amount"], "ratio_to_typical": ratio, "within_1_5x": bool(ratio is not None and ratio <= core.AMOUNT_FACTOR),
            "percentile_in_history": pct, "max_in_history": pos[-1] if pos else None}

def check_domain(conn, vendor_id, sender_address):
    v = core._vendor(conn, vendor_id)
    dom = core._domain(sender_address)
    d = _lev(dom, v["domain"].lower())
    return {"sender_domain": dom, "vendor_domain": v["domain"], "exact_match": d == 0, "edit_distance": d,
            "lookalike_suspect": 0 < d <= 3 or (dom != v["domain"].lower() and re.sub(r"[^a-z]", "", dom.split(".")[0]) == re.sub(r"[^a-z]", "", v["domain"].split(".")[0]))}
