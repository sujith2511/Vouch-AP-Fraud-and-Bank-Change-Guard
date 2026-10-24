"""verify_vendor_web with fake Bright Data responses: no network, no credit spent."""
import json

import pytest

from vouch import core, web_verify as wv
from vouch.agent_interface import LocalClient
from vouch.llm_agent import LLMAgent
from vouch.seed import load_vendors

from conftest import make_email
from test_llm_agent import NO_SHIELD, FakeLLM, submit

# Shape seen in a live response: phone inside knowledge.facts with a list-of-{"text"} value, site only in organic.
LIVE_SHAPE = {
    "knowledge": {"facts": [{"predicate": "kc:/location/location:address", "value": [{"text": "1 Main St, San Francisco, CA"}]},
                            {"predicate": "kc:/local:alt phone", "value": [{"text": "(415) 831-1080"}]}]},
    "organic": [{"link": "https://www.realvendor.com/contact"}, {"link": "https://www.yelp.com/biz/realvendor"}],
}
# Documented shape: business listing in snack_pack.
DOC_SHAPE = {"snack_pack": [{"name": "Real Vendor", "phone": "+1 415-831-1080", "link": "https://realvendor.com",
                             "maps_link": "https://maps.google.com/?cid=1"}]}
REAL = {"name": "Real Vendor", "domain": "realvendor.com", "phone": "(415) 831-1080"}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "test-key")
    monkeypatch.setenv("BRIGHT_DATA_SERP_ZONE", "serp_test")
    wv._cache.clear()


def fake(body, status=200, calls=None):
    def post(url, timeout):
        if calls is not None:
            calls.append(url)
        return status, body
    return post


@pytest.mark.parametrize("serp", [LIVE_SHAPE, DOC_SHAPE])
def test_parses_both_shapes(serp):
    r = wv.verify_vendor_web(REAL, "Please call us at 415-831-1080.", post=fake(serp))
    assert r["status"] == "ok" and r["official_phones"] == ["4158311080"]
    assert r["site_domain_matches_vendor"] is True and r["phone_on_file_listed_online"] is True
    assert r["email_phones_not_listed_online"] == []


def test_flags_callback_number_not_listed_online():
    r = wv.verify_vendor_web(REAL, "New bank details. To confirm call (415) 555-0199.", post=fake(LIVE_SHAPE))
    assert r["email_phones_not_listed_online"] == ["4155550199"]


def test_phone_from_vendors_own_site_counts_but_third_party_does_not():
    serp = {"organic": [{"link": "https://www.realvendor.com/support", "description": "Call 1-800-463-3768 for help."},
                        {"link": "https://scam-directory.example.net/x", "description": "Real Vendor: (415) 555-0199"}]}
    r = wv.verify_vendor_web(REAL, "call (415) 555-0199", post=fake(serp))
    assert r["official_phones"] == ["8004633768"] and r["email_phones_not_listed_online"] == ["4155550199"]


def test_directory_page_ranking_first_does_not_cause_domain_mismatch():
    serp = {"organic": [{"link": "https://www.mapquest.com/us/real-vendor-123"}, {"link": "https://www.realvendor.com/about"}]}
    r = wv.verify_vendor_web(REAL, "", post=fake(serp))
    assert r["official_site"] == "https://www.realvendor.com/about" and r["site_domain_matches_vendor"] is True


def test_no_result_on_vendor_domain_is_a_mismatch():
    serp = {"organic": [{"link": "https://www.mapquest.com/us/real-vendor-123"}]}
    assert wv.verify_vendor_web(REAL, "", post=fake(serp))["site_domain_matches_vendor"] is False


def test_no_official_phone_means_email_phone_unconfirmed():
    serp = {"organic": [{"link": "https://www.realvendor.com/contact", "description": "Contact us online."}]}
    r = wv.verify_vendor_web(REAL, "call (415) 555-0199", post=fake(serp))
    assert r["status"] == "ok" and r["official_phones"] == []
    assert r["email_phones_not_listed_online"] == [] and r["email_phones_unconfirmed"] == ["4155550199"]


def test_fictional_vendor_never_looked_up():
    calls = []
    r = wv.verify_vendor_web({"name": "Acme", "domain": "acme.example"}, "", post=fake(LIVE_SHAPE, calls=calls))
    assert r["status"] == "not_applicable" and calls == []


def test_blocked_and_empty_and_error():
    assert wv.verify_vendor_web(REAL, "", post=fake(None, status=429))["status"] == "blocked"
    assert wv.verify_vendor_web(REAL, "", post=fake({"organic": []}))["status"] == "empty"
    def boom(url, timeout): raise TimeoutError("slow")
    wv._cache.clear()
    assert wv.verify_vendor_web(REAL, "", post=boom)["status"] == "error"


def test_one_search_per_vendor():
    calls = []
    for _ in range(3):
        wv.verify_vendor_web(REAL, "", post=fake(LIVE_SHAPE, calls=calls))
    assert len(calls) == 1 and "brd_json=1" in calls[0]


# ---------------------------------------------------------------- agent integration (real-domain vendor)

@pytest.fixture
def real_item(db, tmp_path):
    v = {"vendor_id": "VR", "legal_name": "Real Vendor", "domain": "realvendor.com", "typical_amount": 1000.0,
         "phone": "(415) 831-1080", "bank": {"bank_name": "Old Bank", "routing": "999000001", "account": "TEST0000001"},
         "split": "dev", "payments": [{"voucher": "P1", "amount": 1000.0, "fiscal_year": 2024}]}
    p = tmp_path / "rv.json"; p.write_text(json.dumps([v])); load_vendors(db, str(p))
    def make(body):
        return core.ingest_item(db, item_id=f"R{len(body)}", vendor_id="VR", email=make_email("realvendor.com", body=body),
                                claim={"invoice_number": "INV-R", "amount": 900.0, "currency": "USD", "claimed_bank": None})
    return make


def run(db_path, item, web_result):
    client = LocalClient(db_path)
    agent = LLMAgent(anthropic_client=FakeLLM([submit(verdict="legit")]), model="test", shield=NO_SHIELD,
                     web=lambda vendor, text: web_result)
    return agent.investigate(client.get_item(item["id"]), client)


def test_agent_blocks_legit_when_email_phone_not_listed(db_path, real_item):
    web = wv.verify_vendor_web(REAL, "call (415) 555-0199", post=fake(LIVE_SHAPE))
    d = run(db_path, real_item("Invoice attached. Questions? Call (415) 555-0199."), web)
    assert d.verdict == "uncertain" and any("not listed online" in r for r in d.reasons)
    assert any(x["tool"] == "verify_vendor_web" for x in d.evidence)


def test_agent_blocks_legit_when_email_phone_unconfirmed(db_path, real_item):
    web = wv.verify_vendor_web(REAL, "call (415) 555-0199", post=fake({"organic": [{"link": "https://realvendor.com"}]}))
    d = run(db_path, real_item("New account. Confirm at (415) 555-0199."), web)
    assert d.verdict == "uncertain" and any("could not be confirmed online" in r for r in d.reasons)


def test_agent_escalates_when_real_vendor_unverified(db_path, real_item):
    d = run(db_path, real_item("Invoice attached."), {"status": "blocked", "provider": "bright_data"})
    assert d.verdict == "uncertain" and any("could not be verified online" in r for r in d.reasons)


def test_agent_allows_legit_when_web_check_agrees(db_path, real_item):
    web = wv.verify_vendor_web(REAL, "", post=fake(LIVE_SHAPE))
    d = run(db_path, real_item("Invoice attached, thanks."), web)
    assert d.verdict == "legit"


def test_fictional_vendors_skip_web_check_in_agent(db_path, mk):
    client = LocalClient(db_path)
    seen = []
    agent = LLMAgent(anthropic_client=FakeLLM([submit(verdict="legit")]), model="test", shield=NO_SHIELD,
                     web=lambda v, t: seen.append(v) or {"status": "ok"})
    d = agent.investigate(client.get_item(mk()["id"]), client)
    assert seen == [] and not any(x["tool"] == "verify_vendor_web" for x in d.evidence)
