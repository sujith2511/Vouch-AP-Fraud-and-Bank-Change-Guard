"""Stage 3 tooling: print writer briefs for case specs, and validate the prose files data/raw/v2_batches/cases_NN.json
(each: {case_id: {"subject","body_text","quoted_history"?}}). All fact checks are done with code."""
import glob, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import *
from checks import check_text, parse_amounts, norm
from history_specs import fmt_amount

SPECS = {s["id"]: s for s in load("data/v2/case_specs.json")}
VEND = {v["vendor_id"]: v for v in load(V2)}
WORDS = {"oneline": (3, 30), "short": (18, 85), "medium": (50, 165), "long": (110, 330)}
BANNED_SYSTEM = re.compile(r"ignore (all )?(previous|prior|above)|ai assistant|system notice|\bassistant\b|approve (this|the) (payment|invoice|change)|mark (it |this )?as (approved|verified)", re.I)
LANG = {"en": "English", "es": "Spanish", "fr": "French", "de": "German"}


def bank_tokens(s):
    b = s["claimed_bank"]
    if not b: return []
    ct = s["change_type"]
    if ct == "account_only": return [b["account"]]
    if ct == "routing_only": return [b["routing_or_iban"]]
    return [b["routing_or_iban"]] + ([b["account"]] if b["account"] != b["routing_or_iban"] else [])


def must_for(s):
    toks = [s["invoice"]["number"]]
    if s["scenario"] in ("po_matched", "po_mismatch_legit") and s["invoice"]["po"]: toks.append(s["invoice"]["po"])
    toks += bank_tokens(s)
    if s["notes"].get("restate_bank_on_file"): toks.append(VEND[s["vendor_id"]]["bank_on_file"]["routing_or_iban"])
    if s["notes"].get("new_remit_address"): toks.append(s["notes"]["new_remit_address"].split(",")[0])
    if s["notes"].get("new_legal_name"): toks.append(s["notes"]["new_legal_name"])
    amts = [] if s["notes"].get("pair_part") in ("routing_number_only",) else [abs(s["invoice"]["amount"])]
    if s["scenario"] in ("fake_invoice_compromised_domain_real_bank",): pass
    return toks, amts


def allowed_emails(s):
    v = VEND[s["vendor_id"]]; a = {s["from_addr"].lower(), s["reply_to"].lower(), s["to"].lower()} | {c.lower() for c in s["cc"]}
    if v["in_master"]:
        a |= {v["primary_contact"]["email"].lower(), v["second_contact"]["email"].lower(), "noreply@" + v["domain"], "billing@" + v["domain"], "ar@" + v["domain"]}
        if v["freemail_contact"]: a.add(v["freemail_contact"]["email"].lower())
    else: a |= {v["primary_contact"]["email"].lower()}
    return a


def brief(ids):
    for cid in ids:
        s = SPECS[cid]; v = VEND[s["vendor_id"]]; at = s["attrs"]; vo = v["voice"]; inv = s["invoice"]; cur_ = inv["currency"]
        lo, hi = WORDS[at["length"]]
        amt = fmt_amount(inv["amount"], cur_, "plain" if v["country"] not in ("DE", "FR") else "symbol", v["country"])
        print(f"\n## {cid} [{s['scenario']} | {s['difficulty']} | {s['split']}] vendor {v['vendor_id']} {v['legal_name']} ({v['country']} {cur_}, {v['industry']})")
        print(f"   FROM {s['from_name']} <{s['from_addr']}> reply-to {s['reply_to']} | TO {s['to']}{' CC ' + ', '.join(s['cc']) if s['cc'] else ''} | {s['attrs']['sent_local_weekday']} {s['sent_local'][11:16]} local | thread={at['thread']} | {LANG[at['language']]} | {lo}-{hi} words | register={at['register']} | footer={at['device_footer']} | urgency={at['urgency']} | noise={','.join(at['noise']) or '-'}")
        print(f"   VENDOR VOICE: greet '{vo['greeting']}', close '{vo['closing']}', sig={vo['signature_style']}, habit={vo['habit']}; phone on file {v['phone_on_file'] or '-'}" if v["in_master"] else f"   (unregistered supplier; contact {v['primary_contact']['name']})")
        print(f"   FACTS invoice {inv['number']} | amount {amt} {cur_} | PO {inv['po'] or '-'} | invoice date {inv['date']} due {inv['due_date']} | lines: " + "; ".join(f"{li['description']} {li['amount']}" for li in inv["line_items"]))
        if s["claimed_bank"]:
            b = s["claimed_bank"]; print(f"   NEW BANK ({s['change_type']}): {b['bank_name']} | routing/IBAN {b['routing_or_iban']} | account {b['account']}" + (f" | BIC {b['swift']}" if b["swift"] else "") + f" | country {b['country']}")
        if s["attachments"]: print("   ATTACHED: " + ", ".join(a["filename"] for a in s["attachments"]))
        content_tells = {"urgency_pressure", "bypass_verification", "no_signed_form_or_prior_notice", "split_bank_details", "unrecognized_third_party", "no_notice_of_assignment_on_file", "executive_impersonation",
                         "unknown_vendor", "no_po", "bank_country_mismatch", "vague_single_line_item", "description_off_profile", "no_po_for_vendor_that_always_uses_po", "no_po_and_no_matching_work"}
        header_tells = {"lookalike_domain", "auth_failures", "reply_to_mismatch", "origin_ip_differs_from_usual", "mailer_differs_from_history", "young_sender_domain", "odd_send_hour", "dkim_missing",
                        "form_signatory_not_an_authorized_contact", "dormant_vendor_resumes", "hidden_prompt_injection", "matches_paid_invoice_except_number", "invoice_number_sequence_jump",
                        "just_under_approval_threshold", "threshold_splitting_pair", "amount_just_under_1_5x_typical", "freemail_sender_not_on_file"}
        ct = [t["id"] for t in s["tells"] if t["id"] in content_tells]; ht = [t["id"] for t in s["tells"] if t["id"] in header_tells]
        if s["label"] == "fraud": print("   CONTENT TELLS (let them show naturally, nothing more): " + (", ".join(ct) or "none") + " | HEADER-ONLY (never mention): " + (", ".join(ht) or "none"))
        else: print("   LEGIT: no suspicious wording. Fraud-looking surface features present in headers/facts: " + (", ".join(s["surface_features"]) or "none"))
        for line in s["narrative"]: print("   NARRATIVE: " + line)
        if at["thread"] in ("reply_in_thread", "reply_all_cc"): print("   QUOTED_HISTORY required: 2-6 lines of the earlier AP/vendor message(s) this replies to (plausible, consistent with facts; no new bank numbers unless noted).")
        if at["thread"] == "forward": print("   QUOTED_HISTORY required: the forwarded message (with From:/Sent:/To:/Subject: lines, fictional names only) that this email forwards.")
        if s["scenario"] == "thread_hijack": print("   QUOTED_HISTORY: genuine earlier exchange; vendor says existing bank ends in " + str(v['bank_on_file']['account'])[-4:] + ".")
        if s.get("pair_with"): print(f"   PAIR with {s['pair_with']} ({s['notes'].get('pair_part') or 'invoice pair'})")


def validate(path):
    data = json.load(open(path)); fails = {}
    for cid, e in data.items():
        s = SPECS.get(cid)
        if not s: fails[cid] = ["unknown id"]; continue
        body = e.get("body_text", ""); q = e.get("quoted_history", "") or ""
        toks, amts = must_for(s)
        bad = check_text(body + "\n" + e.get("subject", ""), allowed_emails(s), s["attrs"]["urgency"] != "none", amts, toks, WORDS[s["attrs"]["length"]], [])
        bad += [f"quoted/forwarded text: {p}" for p in check_text(q, allowed_emails(s) | {"ap@northgate.example"}, True, (), (), None)]
        if BANNED_SYSTEM.search(body + q): bad.append("text addressed to an AI/system")
        if s["attrs"]["thread"] in ("reply_in_thread", "reply_all_cc", "forward") and len(q.strip()) < 25: bad.append("quoted_history required but missing")
        if s["attrs"]["thread"] == "new" and q.strip(): bad.append("quoted_history given for a new thread")
        if s["scenario"] == "thread_hijack" and not q.strip(): bad.append("hijack needs quoted history")
        if s["claimed_bank"] is None and not s["notes"].get("restate_bank_on_file") and re.search(r"\b(routing|iban|swift)\b[^\n]{0,20}\d{6}", body, re.I): bad.append("bank numbers in a no-bank-change email")
        if bad: fails[cid] = bad
    return data, fails


def written():
    got = {}
    for p in sorted(glob.glob("data/raw/v2_batches/cases_*.json")): got.update(json.load(open(p)))
    return got


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "brief": brief(sys.argv[2:])
    elif cmd == "next":
        n = int(sys.argv[2]); got = written(); todo = [i for i in SPECS if i not in got][:n]; brief(todo)
    elif cmd == "check":
        tot = 0
        for p in sorted(glob.glob("data/raw/v2_batches/cases_*.json")):
            d, f = validate(p); tot += len(d); print(p, len(d), "emails;", len(f), "failures"); [print("  ", k, v) for k, v in f.items()]
        print("total written", tot, "of", len(SPECS))
