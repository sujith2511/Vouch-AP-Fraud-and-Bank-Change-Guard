"""Read-only data access for the agent's tools (Sujith defines the tool signatures; these are the implementations).
None of these can change state."""
import re
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
    return {"vendor": {k: v[k] for k in ("vendor_id", "name", "domain", "typical_amount", "phone")} if v else None,
            "bank_on_file": core._mask(v["bank"]) if v else None, "payments": [dict(r) for r in rows]}

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
