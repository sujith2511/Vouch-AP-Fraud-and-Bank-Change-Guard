"""Merge history specs (facts) with the written prose -> data/v2/vendor_email_history.jsonl (agent-visible baseline of past LEGIT mail)."""
import glob, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import *
from history_batches import validate, allowed, VEND, SPECS

def main():
    prose = {}
    for p in sorted(glob.glob("data/raw/v2_batches/history_*.json")):
        d, fails = validate(p)
        if fails: raise SystemExit(f"{p} has failing emails: {list(fails)[:3]}")
        prose.update(d)
    rows = []
    for sid, s in SPECS.items():
        v = VEND[s["vendor_id"]]; e = prose[sid]
        rows.append({"id": sid, "vendor_id": s["vendor_id"], "split": v["split"], "sent_at": s["sent_at"], "sent_at_note": "sender-local time, simulated",
                     "from_name": s["from_name"], "from_addr": s["from_addr"], "from_role": s["from_role"], "to": "ap@northgate.example", "channel": s["channel"],
                     "mailer": v["mailer"], "tone": s["register"], "signature_style": v["voice"]["signature_style"], "device_footer": s["device_footer"], "kind": s["kind"],
                     "subject": e["subject"], "body_text": e["body_text"],
                     "invoice": {"number": s["invoice_number"], "amount": s["amount"], "currency": s["currency"], "po": s["po"]} if s["invoice_number"] else None,
                     "claimed_bank": s["claimed_bank"], "label": "legit",
                     "provenance": {"real_fields": ["amount (from real SF payment, converted)", "po (real SF PO number)"], "simulated_fields": s["simulated"],
                                    "fabricated_fields": ["names", "addresses", "bank details", "prose"], "generator": "prose written directly by Claude in-session in batches; facts fixed and verified by code",
                                    "generated_at": "2026-10-24"}})
    dump_jsonl(rows, "data/v2/vendor_email_history.jsonl")
    from collections import Counter
    per = Counter(r["vendor_id"] for r in rows)
    print(len(rows), "history emails;", "per vendor", min(per.values()), "-", max(per.values()), "| kinds", dict(Counter(r["kind"] for r in rows)))

if __name__ == "__main__": main()
