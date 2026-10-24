import json, re
from pathlib import Path
import pytest
from vouch import seed
from vouch.db import init_db, connect

DOC = json.load(open("data/v2/demo_real_vendors.json"))
CO = DOC["companies"]

def test_shape_and_provenance():
    assert 3 <= len(CO) <= 5
    for c in CO:
        assert c["demo_only"] is True and c["exclude_from_eval"] is True and c["split"] is None
        assert c["sec"]["source_url"].startswith("https://data.sec.gov/submissions/CIK") and c["sec"]["entity_type"] == "operating"
        assert c["sec"]["phone_raw"]
        w = c["website"]
        assert w["verified"] == (w["http_status"] == 200 and c["legal_name"].split()[0].lower().strip(",.") in (w["page_title"] or "").lower())
        assert w["verified"] or w["note"]   # an unverified site must say so
        assert c["phone_check"]["matches_sec_phone"] in (True, False, None) and c["phone_check"]["reason"]

def test_phone_check_is_consistent_with_the_data():
    for c in CO:
        pages = [p for pg in c["contact_pages"] for p in pg["phones"]]
        m = c["phone_check"]["matches_sec_phone"]
        if not pages: assert m is None
        else: assert m == any(p["digits"] == c["sec"]["phone_digits"] for p in pages)

def test_payments_are_exact_spellings_only_and_nothing_is_fabricated():
    for c in CO:
        sf = c["sf_payments"]
        assert sf["count"] == len(sf["payments"]) and sf["found"] == bool(sf["payments"])
        assert {p["name_as_paid"] for p in sf["payments"]} <= set(sf["exact_payee_spellings_used"])
        if not sf["found"]: assert sf["note"] and sf["payments"] == []
        assert all(p["voucher"] for p in sf["payments"])

def test_bank_details_are_fake_test_values():
    for c in CO:
        assert c["bank"]["account"].startswith("TEST") and c["bank"]["routing"].startswith("999") and c["fabricated_fields"] == ["bank"]

def test_no_email_or_injection_in_any_dataset_mentions_these_companies():
    names = set()
    for c in CO:
        names |= {c["legal_name"].lower().replace(",", "").replace(".", ""), c["website"]["url"].split("//")[1].replace("www.", "").lower()}
        names |= {w.lower() for w in re.split(r"[ ,.]+", c["legal_name"]) if len(w) >= 6 and w.lower() not in ("solutions",)}
    blobs = {}
    for f in list(Path("data").glob("*.jsonl")) + list(Path("data/fixtures").glob("*.jsonl")) + [Path("data/injections.json"), Path("data/vendors.json")]:
        blobs[str(f)] = f.read_text().lower()
    hits = [(f, n) for n in names for f, t in blobs.items() if n in t]
    assert hits == [], hits

def test_demo_file_cannot_be_loaded_into_the_eval_db(tmp_path):
    path = str(tmp_path / "d.db"); init_db(path).close(); c = connect(path)
    with pytest.raises(ValueError, match="demo-only"): seed.load_vendors(c, "data/v2/demo_real_vendors.json")
    assert c.execute("SELECT COUNT(*) n FROM vendors").fetchone()["n"] == 0

def test_eval_and_pipeline_never_reference_the_demo_file():
    for f in Path("vouch").glob("*.py"):
        # seed.py names the file only to refuse it; demo.py (live demo code, never the seed/eval path) is the only module that reads it
        assert "demo_real_vendors" not in f.read_text() or f.name in ("seed.py", "demo.py")
