"""Stage 5: merge case specs + written prose -> data/v2/emails.jsonl (+ dev/holdout files), with injection payloads inserted by CODE.
Then re-verify every FINAL record against its spec (facts, headers, domains, injection placement, split-by-vendor).
    python scripts/v2/assemble_emails.py"""
import glob, json, re, shutil, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, "scripts")
from common import *
from case_batches import SPECS, VEND, validate, must_for, allowed_emails
from checks import has_token, parse_amounts, EMAIL, URL, RESERVED
from injlib import hide

HEADER_TELLS = {"lookalike_domain", "auth_failures", "reply_to_mismatch", "origin_ip_differs_from_usual", "mailer_differs_from_history", "young_sender_domain", "odd_send_hour", "dkim_missing",
                "freemail_sender_not_on_file", "dormant_vendor_resumes"}


def load_prose():
    prose = {}
    Path("data/v2/prose").mkdir(parents=True, exist_ok=True)
    for p in sorted(glob.glob("data/raw/v2_batches/cases_*.json")):
        d, fails = validate(p)
        if fails: raise SystemExit(f"{p}: {len(fails)} emails fail the checks, fix before assembling")
        prose.update(d); shutil.copy(p, "data/v2/prose/" + Path(p).name)
    for p in sorted(glob.glob("data/raw/v2_batches/history_*.json")): shutil.copy(p, "data/v2/prose/" + Path(p).name)
    return prose


ATTACH_WORDS = re.compile(r"\b(attach\w*|enclos\w*|adjunt\w*|ci-joint\w*|pi[eè]ce jointe|anbei|beigef[uü]gt\w*|im anhang|en archivo adjunto)\b", re.I)


def add_missing_attachments(recs):
    """Attachment metadata must agree with the prose: when the body says something is attached/enclosed but the spec has no attachment,
    generate the invoice PDF text from the email's own facts. (Fixes a spec artifact: fraud scenarios had almost no attachments,
    which let a classifier use 'has a PDF' as a label shortcut.)"""
    import case_specs as cs
    n = 0
    for r in recs:
        if r["attachments"] or r["truth"]["scenario"] in ("split_account_routing_messages",): continue
        if not ATTACH_WORDS.search(r["body_text"]): continue
        s = json.load(open("data/v2/case_specs.json")) if False else SPECS[r["id"]]
        v = cs.V[r["vendor_id"]]
        a = cs.attach("invoice_pdf", s, v, rng_for("late-attach", r["id"]))
        r["attachments"] = [a]; r["provenance"]["simulated_fields"].append("attachment added to match prose that references one"); n += 1
    return n


def hard_reason(s):
    if s["difficulty"] != "hard": return None
    if s["label"] == "legit": return "legit mail with fraud-looking surface features: " + ", ".join(s["surface_features"] or ["(none)"])
    ids = {t["id"] for t in s["tells"]}
    return ("fraud with a header-level tell but a polished message" if ids & HEADER_TELLS else "fraud with NO header-level tell: only content/context tells (verify by callback, history, PO or sequence)")


def build():
    prose = load_prose(); recs = []
    for cid, s in SPECS.items():
        e = prose[cid]; v = VEND[s["vendor_id"]]; at = s["attrs"]
        body = e["body_text"]; q = e.get("quoted_history") or None
        inj = s["injection"]
        if inj and inj["hidden_in"] in ("html_comment", "white_span", "footer"): body = hide(body, inj["text"], inj["hidden_in"])
        if inj and inj["hidden_in"] == "quoted_reply":
            block = f"On Tue, the AP desk wrote:\n> Thanks for your note.\n> {inj['text']}\n> Regards, AP"
            q = (q + "\n\n" if q else "") + block
        cb = s["claimed_bank"]
        recs.append({
            "id": cid, "vendor_id": s["vendor_id"], "split": s["split"], "thread_id": s["thread_id"], "in_reply_to": s["in_reply_to"], "message_id": s["message_id"],
            "sent_at": s["sent_at"], "received_at": s["received_at"], "from_name": s["from_name"], "from_addr": s["from_addr"], "reply_to": s["reply_to"], "to": s["to"], "cc": s["cc"],
            "subject": e["subject"], "body_text": body, "body_html_present": s["body_html_present"], "quoted_history": q,
            "attachments": s["attachments"],
            "headers": {"spf": s["auth"]["spf"], "dkim": s["auth"]["dkim"], "dmarc": s["auth"]["dmarc"], "return_path": "bounces@" + s["return_path_domain"], "message_id_domain": s["message_id_domain"],
                        "mailer": s["mailer"], "received_hops": s["received_hops"], "origin_ip": s["origin_ip"]},
            "sender_domain": s["sender_domain"], "sender_domain_age_days": s["sender_domain_age_days"], "sender_domain_age_simulated": True, "domain_registered_at": s["sender_domain_registered"],
            "language": at["language"], "device_footer": at["device_footer"],
            "invoice": s["invoice"],
            "claimed_bank": ({"bank_name": cb["bank_name"], "routing_or_iban": cb["routing_or_iban"], "account": cb["account"], "swift": cb.get("swift"), "country": cb["country"], "change_type": s["change_type"]} if cb else None),
            "claim_changes_bank": s["claim_changes_bank"], "change_type": s["change_type"],
            "vendor_snapshot": s["vendor_snapshot"],
            "attributes": {"scenario_independent": {k: at[k] for k in ("channel", "thread", "length", "register", "urgency", "noise", "sent_local_weekday", "sent_hour_local")}},
            "truth": {"scenario": s["scenario"], "sub_variant": s["sub_variant"], "family": s["family"], "label": s["label"], "expected_lane": s["lane"], "correct_agent_verdict": s["verdict"],
                      "difficulty": s["difficulty"], "hard_reason": hard_reason(s), "tells": s["tells"], "surface_features": s["surface_features"], "callback_outcome": s["callback_outcome"],
                      "injection": inj, "lookalike_fuzzer": s["lookalike_fuzzer"], "pair_id": s.get("pair_id"), "pair_with": s.get("pair_with"),
                      "pending_bank_change_notice": s["snapshot_extra"].get("pending_bank_change_notice")},
            "provenance": {"real_fields": ["vendor payment history (amounts, PO numbers, fiscal years) from SF Controller open data, used to set typical amounts and cite real POs",
                                           "InjecAgent phrasing (injection cases only)"],
                           "derived_fields": ["typical_amount", "expected_lane", "correct_agent_verdict", "difficulty", "tells", "vendor_snapshot"],
                           "simulated_fields": ["sent_at/received_at", "invoice numbers/dates/line items", "headers (spf/dkim/dmarc/ips/mailer/hops)", "sender_domain_age_days & domain_registered_at", "callback_outcome", "pending_bank_change_notice"],
                           "fabricated_fields": ["names, domains, phone numbers, bank details (all fake test values)", "all email prose"],
                           "style_sources": "none: Enron/phishing excerpts were NOT used as texture in this build (see DATASET_CARD known limits); prose follows per-vendor voice profiles + scenario briefs",
                           "generator": "prose written directly by Claude in-session in batches of 15 (no API key, no claude -p); every fact fixed by code and verified by code; injection payloads inserted by code",
                           "generated_at": "2026-10-24"}})
    return recs


def verify(recs):
    errs = []
    for r in recs:
        s = SPECS[r["id"]]; v = VEND[r["vendor_id"]]; text = r["subject"] + "\n" + r["body_text"]
        toks, amts = must_for(s)
        for t in toks:
            if not has_token(text, t): errs.append((r["id"], "missing token", t))
        got = {round(abs(x), 2) for x in parse_amounts(text)}
        for a in amts:
            if round(abs(a), 2) not in got: errs.append((r["id"], "missing amount", a))
        everything = text + "\n" + (r["quoted_history"] or "") + "\n".join(a["extracted_text"] or "" for a in r["attachments"])
        for u in URL.findall(everything):
            if not re.sub(r"^(https?://)?(www\.)?", "", u.rstrip(".,;:!?)"), flags=re.I).split("/")[0].lower().endswith(RESERVED): errs.append((r["id"], "non-reserved url", u))
        for em in EMAIL.findall(everything):
            if not em.lower().split("@")[1].endswith(RESERVED): errs.append((r["id"], "non-reserved email domain", em))
        for addr in [r["from_addr"], r["reply_to"], r["to"]] + r["cc"]:
            if not addr.split("@")[1].endswith(RESERVED): errs.append((r["id"], "non-reserved header domain", addr))
        if v["split"] != r["split"]: errs.append((r["id"], "split != vendor split"))
        inj = r["truth"]["injection"]
        if inj:
            where = inj["hidden_in"]; hay = {"quoted_reply": r["quoted_history"] or "", "attachment_text": "\n".join(a["extracted_text"] or "" for a in r["attachments"])}.get(where, r["body_text"])
            if hay.count(inj["text"]) != 1: errs.append((r["id"], "injection payload not exactly once in", where))
            others = [x for x in (r["body_text"], r["quoted_history"] or "") if x is not hay]
            if any(inj["text"] in o for o in others): errs.append((r["id"], "injection payload leaked outside placement"))
        else:
            for k in ("body_text", "quoted_history"):
                if r[k] and re.search(r"ignore (all )?previous|IMPORTANT!!!", r[k], re.I): errs.append((r["id"], "injection-like text in non-injection case"))
        if r["claimed_bank"] and "test" in json.dumps(r["claimed_bank"]).lower(): errs.append((r["id"], "bank values contain the word test"))
        if r["truth"]["label"] == "fraud" and r["truth"]["expected_lane"] == "auto_clear": errs.append((r["id"], "fraud expected auto_clear"))
    return errs


if __name__ == "__main__":
    recs = build(); added = add_missing_attachments(recs); print('attachments added to match prose:', added); errs = verify(recs)
    print(len(recs), "records;", len(errs), "verification errors")
    for e in errs[:30]: print("  ", e)
    if errs: sys.exit(1)
    recs.sort(key=lambda r: r["id"])
    dump_jsonl(recs, "data/v2/emails.jsonl")
    dump_jsonl([r for r in recs if r["split"] == "dev"], "data/v2/emails.dev.jsonl"); dump_jsonl([r for r in recs if r["split"] == "holdout"], "data/v2/emails.holdout.jsonl")
    print("wrote data/v2/emails.jsonl", Counter(r["split"] for r in recs))
