import collections, json, subprocess, sys
from datetime import date

V = json.load(open("data/v2/vendors.v2.json"))
REAL = [v for v in V if v["in_master"]]
PAY = [json.loads(l) for l in open("data/v2/payments.v2.jsonl")]
HIST = [json.loads(l) for l in open("data/v2/vendor_email_history.jsonl")]

def test_counts_and_international_share():
    assert len(REAL) == 60 and len(V) - len(REAL) == 24
    intl = [v for v in REAL if v["country"] != "US"]
    assert len(intl) == 12 and {v["currency"] for v in intl} == {"EUR", "GBP", "CAD"}
    assert all(v["payment_method_on_file"] == "wire" for v in intl)

def test_split_is_by_vendor_and_about_65_35():
    s = collections.Counter(v["split"] for v in REAL)
    assert s["holdout"] / 60 in (21 / 60, 22 / 60, 20 / 60) and s["dev"] + s["holdout"] == 60
    assert {p["vendor_id"] for p in PAY} <= {v["vendor_id"] for v in REAL}

def test_fake_banks_phones_and_no_test_word_in_bank_fields():
    for v in REAL:
        b = v["bank_on_file"]; assert b["routing_or_iban"] and b["account"]
        assert "TEST" not in json.dumps(b).upper().replace("ZZBK", "")  # emails must never leak the word test via bank fields
        assert v["tax_id"]["fake"] is True and v["tax_id"]["id"].startswith("99-")
        if v["country"] == "US": assert b["routing_or_iban"].startswith("999") and v["phone_on_file"].startswith("(415) 555-01")
        else: assert "00ZZBK" in b["routing_or_iban"] or v["country"] == "CA"

def test_payments_dates_are_simulated_and_consistent():
    assert all(p["provenance"]["dates_simulated"] for p in PAY)
    for p in PAY:
        assert p["invoice_date"] <= p["due_date"] and p["invoice_date"] < p["paid_date"] <= "2026-10-20"
    assert len({(p["vendor_id"], p["invoice_number"]) for p in PAY}) == len(PAY)
    wd = collections.Counter(date.fromisoformat(p["invoice_date"]).weekday() for p in PAY)
    assert wd[5] + wd[6] < 0.03 * len(PAY)                      # weekdays dominate
    paid_wd = collections.Counter(date.fromisoformat(p["paid_date"]).weekday() for p in PAY)
    assert paid_wd[5] + paid_wd[6] < 0.03 * len(PAY)

def test_real_fields_preserved_from_v1():
    v1 = {v["vendor_id"]: {(x["voucher"], x["amount"], x["fiscal_year"]) for x in v["payments"]} for v in json.load(open("data/vendors.json"))}
    assert all((p["voucher"], p["amount_usd"], p["fiscal_year"]) in v1[p["vendor_id"]] for p in PAY)
    assert len(PAY) == sum(len(x) for x in [json.load(open("data/vendors.json"))]) or len(PAY) == sum(len(v["payments"]) for v in json.load(open("data/vendors.json")))

def test_history_per_vendor_between_8_and_25_and_all_legit():
    per = collections.Counter(h["vendor_id"] for h in HIST)
    assert set(per) == {v["vendor_id"] for v in REAL} and min(per.values()) >= 8 and max(per.values()) <= 25
    assert all(h["label"] == "legit" and h["body_text"].strip() for h in HIST)
    withbank = {v["vendor_id"] for v in REAL if v["bank_change_history"]}
    assert {h["vendor_id"] for h in HIST if h["kind"] == "bank_change_notice"} == withbank

def test_vendor_master_build_is_deterministic(tmp_path):
    import hashlib
    h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
    before = (h("data/v2/vendors.v2.json"), h("data/v2/payments.v2.jsonl"))
    subprocess.run([sys.executable, "-I", "scripts/v2/vendor_master.py"], check=True, capture_output=True)
    assert (h("data/v2/vendors.v2.json"), h("data/v2/payments.v2.jsonl")) == before
