"""Specs (facts only, no prose) for each vendor's past legitimate emails: data/v2/history_specs.json.
The prose is written in batches (data/raw/v2_batches/history_*.json) and merged by assemble_history.py."""
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import *

CUR = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "CA$"}
TZ_HOURS = {"US": (8, 17), "DE": (7, 16), "FR": (7, 16), "GB": (7, 16), "CA": (8, 17)}   # hours in sender-local time; sent_at is local, tz recorded separately


def fmt_amount(a, cur, style, country):
    if country in ("DE", "FR") and style != "code":
        s = f"{abs(a):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{'-' if a < 0 else ''}{s} €"
    if style == "code": return f"{'-' if a < 0 else ''}{cur} {abs(a):,.2f}"
    if style == "plain": return f"{a:.2f}"
    return f"{'-' if a < 0 else ''}{CUR[cur]}{abs(a):,.2f}"


def n_history(v, r):
    base = {"weekly": 22, "monthly": 14, "quarterly": 9, "ad hoc": 8}[v["invoice_cadence"]]
    return max(8, min(25, base + r.randint(-3, 4) + (2 if v["size_band"] == "large" else 0)))


def build():
    vendors = [v for v in load(V2) if v["in_master"]]
    pays = defaultdict(list)
    for p in load_jsonl(PAYMENTS): pays[p["vendor_id"]].append(p)
    specs = []
    for v in vendors:
        r = rng_for("history", v["vendor_id"])
        ps = [p for p in pays[v["vendor_id"]] if p["doc_type"] == "invoice"]
        ps.sort(key=lambda p: p["invoice_date"])
        end = min(CASE_START - timedelta(days=1), date.fromisoformat(ps[-1]["invoice_date"]) + timedelta(days=45))
        ps = [p for p in ps if date.fromisoformat(p["invoice_date"]) <= end]
        n = n_history(v, r)
        has_bank = bool(v["bank_change_history"])
        n_bank = 1 if has_bank else 0
        n_inv = min(len(ps), round((n - n_bank) * 0.7))
        chosen = ps[-n_inv:] if n_inv else []
        rows = []
        portal = v["preferred_contact_channel"] == "portal"
        for p in chosen:
            d = date.fromisoformat(p["invoice_date"]) + timedelta(days=r.choice([0, 0, 1, 1, 2]))
            rows.append({"kind": "portal_notification" if portal and r.random() < 0.8 else "invoice", "date": next_weekday(d), "invoice": p["invoice_number"], "amount": p["amount"],
                         "po": p["po_number"] if (p["po_number"] and r.random() < 0.7) else None, "doc_type": p["doc_type"]})
        TOPICS = ["holiday office hours", "annual price list update (no change to payment details)", "new portal address for downloading invoices", "W-9 refresh available on request",
                  "staff change on their billing team", "reminder of net terms and late-fee policy", "year-end invoicing cutoff dates", "change of their invoice PDF format"]
        by_inv = {x["invoice"]: x for x in rows if x["invoice"]}
        pool = [x for x in rows if x["kind"] in ("invoice", "portal_notification")]
        guard = 0
        while len(rows) < n - n_bank and guard < 200:
            guard += 1
            k = r.choice(["statement", "status_question", "notice", "remittance_question", "notice"] + (["statement"] if v["invoice_cadence"] in ("monthly", "weekly") else []))
            if k in ("status_question", "remittance_question") and pool:
                ref = r.choice(pool); d = ref["date"] + timedelta(days=r.randint(7, 60))
                if d > end: continue
                rows.append({"kind": k, "date": next_weekday(d), "invoice": ref["invoice"], "amount": ref["amount"], "po": None, "doc_type": None})
            elif k == "statement" and pool:
                d = next_weekday(pool[0]["date"] + timedelta(days=r.randint(30, 600)))
                if d > end: continue
                recent = [x for x in pool if timedelta(days=0) < d - x["date"] <= timedelta(days=40)]
                if not recent: continue
                rows.append({"kind": k, "date": d, "invoice": None, "amount": round(sum(x["amount"] for x in recent), 2), "po": None, "doc_type": None, "n_open": len(recent)})
            else:
                rows.append({"kind": "notice", "date": next_weekday(end - timedelta(days=r.randint(5, 700))), "invoice": None, "amount": None, "po": None, "doc_type": None, "topic": r.choice(TOPICS).replace("W-9", "W-8BEN-E") if v["country"] != "US" else r.choice(TOPICS)})
        if has_bank:
            ch = v["bank_change_history"][-1]; d = next_weekday(date.fromisoformat(ch["changed_at"]) - timedelta(days=r.randint(14, 30)))
            rows.append({"kind": "bank_change_notice", "date": d, "invoice": None, "amount": None, "po": None, "doc_type": None, "bank": ch["to"], "prior_bank_last4": str(ch["from"]["account"])[-4:], "ticket": ch["ticket"]})
        rows.sort(key=lambda x: x["date"])
        lo, hi = TZ_HOURS[v["country"]]
        senders = [("primary", v["primary_contact"]["name"], v["primary_contact"]["email"])]
        senders.append(("second", v["second_contact"]["name"], v["second_contact"]["email"]))
        if v["freemail_contact"]: senders.append(("freemail", v["primary_contact"]["name"], v["freemail_contact"]["email"]))
        sw = {"primary": 70, "second": 22, "freemail": 25}
        style = r.choice(["symbol", "symbol", "code", "plain"]) if v["voice"]["habit"] != "writes numbers with the currency code (USD 1,234.00)" else "code"
        for i, row in enumerate(rows, 1):
            who = weighted(r, [(s, sw[s[0]]) for s in senders]) if row["kind"] != "bank_change_notice" else senders[0]
            noreg = row["kind"] == "portal_notification"
            reg = "portal_notification" if noreg else (v["voice"]["register"] if r.random() < 0.85 else "neutral")
            if reg == "portal_notification" and not noreg: reg = "neutral"
            sent = datetime(row["date"].year, row["date"].month, row["date"].day, r.randint(lo, hi), r.randint(0, 59))
            specs.append({"id": f"H-{v['vendor_id']}-{i:02d}", "vendor_id": v["vendor_id"], "kind": row["kind"], "sent_at": sent.isoformat(timespec="minutes"), "weekday": sent.strftime("%a"),
                          "from_role": who[0], "from_name": who[1], "from_addr": "noreply@" + v["domain"] if noreg else who[2], "channel": "portal" if noreg else "email",
                          "register": reg, "device_footer": v["voice"]["device"] if (v["voice"]["device"] != "desktop" and r.random() < 0.6) else "none",
                          "invoice_number": row["invoice"], "amount": row["amount"], "amount_text": fmt_amount(row["amount"], v["currency"], style, v["country"]) if row["amount"] is not None else None,
                          "currency": v["currency"], "po": row["po"], "topic": row.get("topic"), "n_open": row.get("n_open"), "claimed_bank": row.get("bank"), "prior_bank_last4": row.get("prior_bank_last4"), "ticket": row.get("ticket"),
                          "simulated": ["sent_at", "invoice_number", "amount(currency conversion)", "sender behaviour"]})
    return specs


if __name__ == "__main__":
    s = build(); dump(s, "data/v2/history_specs.json")
    from collections import Counter
    per = Counter(x["vendor_id"] for x in s)
    print(len(s), "history specs; per vendor min/max", min(per.values()), max(per.values()), "| kinds", Counter(x["kind"] for x in s))
