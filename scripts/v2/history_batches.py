"""Print briefs for history emails and validate / merge batch files written to data/raw/v2_batches/history_NN.json."""
import glob, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import *
from checks import check_text

SPECS = {s["id"]: s for s in load("data/v2/history_specs.json")}
VEND = {v["vendor_id"]: v for v in load(V2)}


def brief(vids):
    for vid in vids:
        v = VEND[vid]; vo = v["voice"]
        print(f"\n## {vid} {v['legal_name']} | {v['country']} {v['currency']} | {v['industry']} | size={v['size_band']} | channel={v['preferred_contact_channel']}")
        print(f"   VOICE: register={vo['register']}; greet='{vo['greeting']}'; close='{vo['closing']}'; sig={vo['signature_style']}; habit={vo['habit']}; ~{vo['avg_words']} words")
        print(f"   people: primary {v['primary_contact']['name']} ({v['primary_contact']['role']}); second {v['second_contact']['name']} ({v['second_contact']['role']}); phone {v['phone_on_file']}; domain {v['domain']}")
        for s in SPECS.values():
            if s["vendor_id"] != vid: continue
            bits = [s["id"], f"{s['weekday']} {s['sent_at'][:16]}", f"{s['from_name'].split()[0]}({s['from_role']})", s["kind"], f"reg={s['register']}"]
            if s["invoice_number"]: bits.append(f"inv {s['invoice_number']}")
            if s["amount_text"]: bits.append(s["amount_text"])
            if s["po"]: bits.append(f"PO {s['po']}")
            if s["topic"]: bits.append(f"topic: {s['topic']}")
            if s["kind"] == "statement": bits.append(f"open items: {s['n_open']}")
            if s["device_footer"] != "none": bits.append(f"footer={s['device_footer']}")
            if s["claimed_bank"]:
                b = s["claimed_bank"]; bits.append(f"NEW BANK {b['bank_name']} / {b['routing_or_iban']} / {b['account']}" + (f" / {b['swift']}" if b['swift'] else "") + f"; old acct ends {s['prior_bank_last4']}; ref {s['ticket']}")
            print("  " + " | ".join(bits))


def allowed(s):
    v = VEND[s["vendor_id"]]
    a = {s["from_addr"].lower(), v["primary_contact"]["email"].lower(), v["second_contact"]["email"].lower(), "ap@northgate.example"}
    if v["freemail_contact"]: a.add(v["freemail_contact"]["email"].lower())
    a.add("noreply@" + v["domain"]); a.add("ar@" + v["domain"]); a.add("billing@" + v["domain"])
    return a


def validate(batch_path):
    data = json.load(open(batch_path)); fails = {}
    for sid, e in data.items():
        s = SPECS.get(sid)
        if not s: fails[sid] = ["unknown id"]; continue
        text = e.get("subject", "") + "\n" + e.get("body_text", "")
        toks = [s["invoice_number"]] if s["invoice_number"] else []
        if s["claimed_bank"]:
            toks += [s["claimed_bank"]["routing_or_iban"], s["claimed_bank"]["account"]] if s["claimed_bank"]["routing_or_iban"] != s["claimed_bank"]["account"] else [s["claimed_bank"]["account"]]
        amts = [s["amount"]] if s["amount"] is not None and s["kind"] != "statement" else []
        bad = check_text(text, allowed(s), False, amts, toks, (6, 220))
        if s["kind"] == "statement" and s["amount"] is not None and not any(abs(x) > 0 for x in [1]): pass
        if bad: fails[sid] = bad
    return data, fails


if __name__ == "__main__":
    if sys.argv[1] == "brief": brief(sys.argv[2:])
    elif sys.argv[1] == "check":
        for p in sorted(glob.glob("data/raw/v2_batches/history_*.json")):
            d, f = validate(p); print(p, len(d), "emails;", len(f), "failures"); [print("  ", k, v) for k, v in f.items()]
