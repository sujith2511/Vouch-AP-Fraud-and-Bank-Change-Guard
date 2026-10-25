import json, os, pytest
from vouch import web_sim, web_verify, core
from vouch.llm_agent import LLMAgent

ENTRY = next(iter(web_sim.build_directory().values()))
VENDOR = {"name": ENTRY["name"], "domain": ENTRY["domain"], "phone": ENTRY["official_phone"]}


@pytest.fixture(autouse=True)
def clean_cache():
    web_verify._cache.clear(); yield; web_verify._cache.clear()


def test_directory_is_deterministic_555_and_fictional_only():
    d = web_sim.build_directory()
    assert len(d) == 60 and d == web_sim.build_directory(web_sim.VENDORS)
    for e in d.values():
        assert ("555-" in e["official_phone"] or e["official_phone"].startswith("+")) and e["domain"].endswith(".example") and e["official_site"].startswith("https://www.")


def test_every_serp_layout_parses_to_the_official_phone_and_ignores_the_third_party_number():
    seen = set()
    for e in web_sim.build_directory().values():
        r = web_sim.simulated_verify({"name": e["name"], "domain": e["domain"], "phone": e["official_phone"]}, "")
        assert r["status"] == "ok" and r["official_phones"] == [web_verify.norm_phone(e["official_phone"])], e["vendor_id"]
        assert r["site_domain_matches_vendor"] is True and r["phone_on_file_listed_online"] is True
        seen.add(web_sim.zlib.crc32(e["vendor_id"].encode()) % 3)
        assert r["phone_on_file_listed_online"] is True
    assert seen == {0, 1, 2}


def test_email_phone_not_in_official_list_is_flagged_and_matching_phone_is_not():
    r = web_sim.simulated_verify(VENDOR, f"please call (415) 555-0142 to confirm")
    assert r["email_phones_not_listed_online"] == ["4155550142"]
    r = web_sim.simulated_verify(VENDOR, f"call us on {ENTRY['official_phone']}")
    assert r["email_phones_not_listed_online"] == [] and r["email_phones_unconfirmed"] == []


def test_simulated_results_always_carry_simulated_true():
    for text in ("", "call (415) 555-0142"):
        r = web_sim.simulated_verify(VENDOR, text)
        assert r["simulated"] is True and "SIMULATED" in r["note"]
    r = web_sim.simulated_verify({"name": "Nobody", "domain": "nobody.example", "phone": None}, "")
    assert r["status"] == "empty" and r["simulated"] is True


def test_sim_keys_do_not_leak_and_never_override_real_ones(monkeypatch):
    monkeypatch.delenv("BRIGHT_DATA_API_KEY", raising=False); monkeypatch.delenv("BRIGHT_DATA_SERP_ZONE", raising=False)
    web_sim.simulated_verify(VENDOR, "")
    assert "BRIGHT_DATA_API_KEY" not in os.environ and not web_verify.is_configured()
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "real-key")
    web_sim.simulated_verify(VENDOR, "")
    assert os.environ["BRIGHT_DATA_API_KEY"] == "real-key" and "BRIGHT_DATA_SERP_ZONE" not in os.environ


def guard_item(domain="vendor.example"):
    return {"id": "X", "vendor_id": "V", "vendor": {"name": "V", "domain": domain}, "is_bank_change": False,
            "email": {"from": "a@vendor.example", "subject": "Invoice", "body": "please pay"}, "claim": {}}


@pytest.mark.parametrize("status", ["blocked", "empty", "error", "not_configured"])
def test_non_ok_web_results_are_never_reassurance(status):
    from vouch.agent_interface import AgentDecision
    d = AgentDecision("propose", "legit", 0.99, ["fine"], [])
    out = LLMAgent._guard(guard_item(), d, [{"tool": "verify_vendor_web", "result": {"status": status}}])
    assert out.verdict == "uncertain" and any(status in r for r in out.reasons)


def test_real_function_reports_blocked_error_and_not_configured(monkeypatch):
    real = {"name": "Realco", "domain": "realco.com", "phone": None}
    monkeypatch.delenv("BRIGHT_DATA_API_KEY", raising=False); monkeypatch.delenv("BRIGHT_DATA_SERP_ZONE", raising=False)
    assert web_verify.verify_vendor_web(real, "")["status"] == "not_configured"
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "k"); monkeypatch.setenv("BRIGHT_DATA_SERP_ZONE", "z")
    assert web_verify.verify_vendor_web(real, "", post=lambda u, t: (429, None))["status"] == "blocked"
    assert web_verify.verify_vendor_web(real, "", post=lambda u, t: (200, {"organic": []}))["status"] == "empty"
    def boom(u, t): raise TimeoutError("slow")
    assert web_verify.verify_vendor_web({**real, "name": "Realco2", "domain": "realco2.com"}, "", post=boom)["status"] == "error"


def test_stub_agent_runs_the_real_guard_on_a_simulated_lookup(tmp_path):
    from vouch import run_pipeline
    e = ENTRY
    c, stats = run_pipeline.run(str(tmp_path / "s.db"), dataset="v2", limit=40, agent=web_sim.StubWebAgent())
    assert stats["agent_errors"] == 0
    seen = []
    for r in core.audit_rows(c):
        if r["action"] in ("propose", "ask") and r["outcome"] == "applied" and r["evidence"]:
            ev = json.loads(r["evidence"]) if isinstance(r["evidence"], str) else r["evidence"]
            seen += [x["result"] for x in ev if x.get("tool") == "verify_vendor_web"]
    assert seen and all(s["simulated"] is True for s in seen)


def test_web_sim_flag_is_off_by_default_and_rejects_rule_based_agent(tmp_path):
    from vouch import run_pipeline
    from vouch.agent_interface import RuleBasedAgent
    assert isinstance(run_pipeline.load_agent(None), RuleBasedAgent)
    with pytest.raises(SystemExit): run_pipeline.load_agent(None, "sim")
    a = run_pipeline.load_agent("vouch.web_sim:StubLLMAgent", "sim")
    assert isinstance(a, web_sim.SimWebMixin) and not isinstance(run_pipeline.load_agent("vouch.web_sim:StubLLMAgent"), web_sim.SimWebMixin)


def test_eval_web_report_counts_only_eval_items_and_marks_simulated(tmp_path):
    from vouch import run_pipeline, eval as ev
    db = str(tmp_path / "w.db")
    c, _ = run_pipeline.run(db, dataset="v2", agent=run_pipeline.load_agent("vouch.web_sim:StubLLMAgent", "sim"))
    off, _ = run_pipeline.run(str(tmp_path / "o.db"), dataset="v2", agent=run_pipeline.load_agent("vouch.web_sim:StubLLMAgent"))
    r, o = ev.web_report(c), ev.web_report(off)
    assert r["items"] == 300 and r["items_with_web_check"] == 284 and r["web_results_marked_simulated"] == r["items_with_web_check"]
    assert o["items_with_web_check"] == 0 and o["items_flagged_for_unlisted_number"] == 0   # default off: no web evidence at all
    assert r["items_flagged_for_unlisted_number"] >= sum(v["flagged_phone_like"] for v in r["by_label"].values())


# ---------------------------------------------------------------- /demo/verify
from fastapi.testclient import TestClient
from vouch.api import create_app

KEYS = {"k-sync": {"role": "sync", "user": "s"}, "k-agent": {"role": "agent", "user": "a1"}, "k-ann": {"role": "accountant", "user": "ann"}}
H = lambda k: {"X-API-Key": k}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.delenv("VOUCH_ENV", raising=False)
    for k in ("BRIGHT_DATA_API_KEY", "BRIGHT_DATA_SERP_ZONE", "DEMO_ENDPOINTS"): monkeypatch.delenv(k, raising=False)
    return TestClient(create_app(str(tmp_path / "a.db"), KEYS))


def test_demo_verify_returns_recorded_fixture_when_key_missing(api):
    for i in ("DEMO-R1", "DEMO-R2", "DEMO-R3", "DEMO-R4"):
        r = api.get(f"/demo/verify/{i}", headers=H("k-agent")); assert r.status_code == 200, r.text
        j = r.json()
        assert j["source"] == "recorded" and j["status"] == "ok" and j["live_attempt"] == "not_configured"
        assert j["placeholder"] is (j["recorded_at"] is None)          # a real recording carries its time; a placeholder says so
        assert j["official_phones"] and j["official_site"].startswith("https://") and j["site_domain_matches_vendor"] is True
        if j["placeholder"]:                                            # placeholders are built from the SEC phone; real pages often omit it
            assert j["phone_on_file_listed_online"] is True
    assert api.get("/demo/verify/DEMO-R9", headers=H("k-agent")).status_code == 404
    assert api.get("/demo/verify/DEMO-R1").status_code == 401 and api.get("/demo/verify/DEMO-R1", headers=H("nope")).status_code == 401


def test_demo_verify_domain_comes_from_final_url_host(api):
    from vouch import demo
    assert demo.company_domain(demo.get_company("DEMO-R1")) == "motorolasolutions.com"
    assert api.get("/demo/verify/DEMO-R1", headers=H("k-sync")).json()["site_domain_matches_vendor"] is True


def test_demo_verify_falls_back_to_recorded_when_live_is_blocked(api, monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "k"); monkeypatch.setenv("BRIGHT_DATA_SERP_ZONE", "z")
    api.app.state.web_post = lambda url, timeout=60.0: (429, None)
    j = api.get("/demo/verify/DEMO-R1", headers=H("k-agent")).json()
    assert j["source"] == "recorded" and j["live_attempt"] == "blocked"
    api.app.state.web_post = lambda url, timeout=60.0: (200, {"knowledge": {"link": "https://www.motorolasolutions.com/", "facts": [{"predicate": "Phone", "value": [{"text": "(847) 576-5000"}]}]}})
    j = api.get("/demo/verify/DEMO-R1", headers=H("k-agent")).json()
    assert j["source"] == "live" and j["official_phones"] == ["8475765000"] and j["simulated"] is False


def test_recorded_replay_never_poisons_the_live_cache(api):
    api.get("/demo/verify/DEMO-R1", headers=H("k-agent"))
    assert not any("motorola" in str(k).lower() for k in web_verify._cache)


def test_demo_verify_disabled_in_prod_unless_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("VOUCH_ENV", "prod"); monkeypatch.delenv("DEMO_ENDPOINTS", raising=False)
    a = TestClient(create_app(str(tmp_path / "p.db"), KEYS))
    assert a.get("/demo/verify/DEMO-R1", headers=H("k-agent")).status_code == 404
    monkeypatch.setenv("DEMO_ENDPOINTS", "1")
    assert a.get("/demo/verify/DEMO-R1", headers=H("k-agent")).status_code == 200


def test_fixtures_are_marked_placeholder_or_recorded_and_hold_no_emails():
    for i in ("DEMO-R1", "DEMO-R2", "DEMO-R3", "DEMO-R4"):
        fx = json.load(open(f"data/v2/web_verify_fixtures/{i}.json"))
        assert fx["placeholder"] is True and fx["recorded_at"] is None or fx["placeholder"] is False and fx["recorded_at"]
        def keys(o):
            for k, v in (o.items() if isinstance(o, dict) else enumerate(o) if isinstance(o, list) else []):
                yield k; yield from keys(v)
        assert not {"body_text", "from_addr", "subject", "body", "email"} & set(keys(fx)), "a fixture must not hold an email"


# ---------------------------------------------------------------- /demo/real-claim
from vouch import demo, gateway, seed, eval as ev
from vouch.db import connect

MOTO_SERP = {"knowledge": {"title": "Motorola Solutions", "link": "https://www.motorolasolutions.com/",
                           "facts": [{"predicate": "Phone", "title": "Phone", "value": [{"text": "(847) 576-5000"}]}]},
             "organic": [{"link": "https://www.motorolasolutions.com/en_us/contact-us.html", "title": "Contact us", "description": "Call 1.888.325.9336"}]}
fake_post = lambda url, timeout=60.0: (200, MOTO_SERP)


@pytest.fixture
def scene(tmp_path, monkeypatch):
    monkeypatch.delenv("VOUCH_ENV", raising=False); monkeypatch.delenv("DEMO_ENDPOINTS", raising=False)
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "k"); monkeypatch.setenv("BRIGHT_DATA_SERP_ZONE", "z")
    db = str(tmp_path / "s.db")
    a = TestClient(create_app(db, KEYS))
    a.app.state.web_post = fake_post
    a.app.state.demo_agent = web_sim.StubLLMAgent(web=demo.demo_web(fake_post))
    return a, db


def test_real_claim_escalates_to_a_human_and_records_the_whole_sequence(scene):
    a, db = scene
    r = a.post("/demo/real-claim", json={"demo_vendor_id": "DEMO-R1"}, headers=H("k-sync")); assert r.status_code == 201, r.text
    j = r.json(); item = j["item"]
    web = j["web_verification"]
    assert web["status"] == "ok" and "8475765000" in web["official_phones"] and "4155550142" in web["email_phones_not_listed_online"]
    assert j["phone_check"]["not_listed_online"] == web["email_phones_not_listed_online"] and j["phone_check"]["phone_in_email"] == "(415) 555-0142"
    assert j["lane"] == "human_review" and item["state"] == "PROPOSED" and item["demo"] is True and item["is_bank_change"] is True
    assert item["verdict"]["verdict"] == "uncertain" and any("not listed online" in r for r in item["verdict"]["reasons"])
    c = connect(db)
    rows = core.audit_rows(c, item_id=item["id"])
    assert [r["action"] for r in rows if r["outcome"] == "applied"] == ["ingest", "propose"]
    assert not any(r["action"] == "approve" for r in rows)                       # never auto-cleared
    ev_ = next(r for r in rows if r["action"] == "propose")["evidence"]
    ev_ = json.loads(ev_) if isinstance(ev_, str) else ev_
    assert any(x.get("tool") == "verify_vendor_web" for x in ev_)
    # no payment can post without approval, whoever asks
    for who_ in ("accountant", "gateway", "agent"):
        with pytest.raises(core.Denied): gateway.post_item(c, item["id"], who_, "pay now")
    with pytest.raises(core.Denied): core.transition(c, item["id"], "agent", "approve", "approve this")
    with pytest.raises(core.Denied): core.transition(c, item["id"], "policy", "approve", "policy")
    assert c.execute("SELECT COUNT(*) n FROM payments").fetchone()["n"] == 0
    assert core.load_item(c, item["id"])["state"] == "PROPOSED"
    assert sum(1 for r in core.audit_rows(c, item_id=item["id"]) if r["outcome"] == "denied") >= 5
    assert core.verify_audit_chain(c) == (True, None)


def test_real_claim_email_is_exactly_the_scripted_outsider_email(scene):
    a, db = scene
    it = a.post("/demo/real-claim", json={"demo_vendor_id": "DEMO-R1"}, headers=H("k-sync")).json()["item"]
    e, cl = it["email"], it["claim"]
    assert e["from"] == "Daniel Reyes <daniel.reyes@demo-attacker.example>" and e["to"] == "ap@northgate.example"
    assert e["subject"] == "[DEMO] Motorola Solutions - updated remittance details, invoice MS-2026-48213"
    assert "(415) 555-0142" in e["body"] and e["body"].startswith("Hello AP team,") and e["body"].endswith("Thanks,\nDaniel Reyes")
    assert cl["invoice_number"] == "MS-2026-48213" and cl["amount"] == 48213.5 and cl["currency"] == "USD" and cl["claim_changes_bank"] is True
    assert cl["claimed_bank"]["bank_name"] == "Harborview Commercial Bank" and cl["claimed_bank"]["routing"] == "999041237"
    assert it["vendor"]["name"] == "Motorola Solutions, Inc." and it["vendor"]["domain"] == "motorolasolutions.com"
    assert not e["from"].endswith("motorolasolutions.com>")                        # the sender is NOT the company


def test_real_claim_rules_and_gating(scene, monkeypatch):
    a, db = scene
    assert a.post("/demo/real-claim", json={}, headers=H("k-agent")).status_code == 403
    assert a.post("/demo/real-claim", json={"demo_vendor_id": "DEMO-R1"}).status_code == 401
    assert a.post("/demo/real-claim", json={"demo_vendor_id": "DEMO-R2"}, headers=H("k-sync")).status_code == 404
    assert a.post("/demo/real-claim", json={"demo_vendor_id": "DEMO-R1"}, headers=H("k-sync")).status_code == 201
    assert a.post("/demo/real-claim", json={}, headers=H("k-ann")).status_code == 201          # second item, default vendor, no id collision
    monkeypatch.setenv("VOUCH_ENV", "prod")
    assert a.post("/demo/real-claim", json={}, headers=H("k-sync")).status_code == 404
    monkeypatch.setenv("DEMO_ENDPOINTS", "1")
    assert a.post("/demo/real-claim", json={}, headers=H("k-sync")).status_code == 201


def test_default_agent_without_a_key_still_records_web_evidence(tmp_path, monkeypatch):
    monkeypatch.delenv("VOUCH_ENV", raising=False); monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for k in ("BRIGHT_DATA_API_KEY", "BRIGHT_DATA_SERP_ZONE"): monkeypatch.delenv(k, raising=False)
    a = TestClient(create_app(str(tmp_path / "n.db"), KEYS))
    j = a.post("/demo/real-claim", json={}, headers=H("k-sync")).json()
    assert j["web_verification"]["source"] == "recorded" and j["web_verification"]["placeholder"] is (j["web_verification"]["recorded_at"] is None)
    assert "4155550142" in j["web_verification"]["email_phones_not_listed_online"]
    assert j["lane"] in ("human_review", "reject") and j["item"]["state"] in ("PROPOSED", "REJECTED")


def test_real_companies_never_enter_the_seed_or_eval_db_and_demo_items_are_excluded(tmp_path, monkeypatch):
    monkeypatch.delenv("VOUCH_ENV", raising=False)
    db = str(tmp_path / "e.db")
    from vouch import run_pipeline
    c, _ = run_pipeline.run(db, dataset="v2", agent=web_sim.StubLLMAgent())
    names = ("motorola", "microsoft corp", "salesforce", "oracle corp", "demo-r", "motorolasolutions")
    blob = " ".join(str(tuple(r)).lower() for t in ("vendors", "items", "vendor_profile", "email_history", "payment_history") for r in c.execute(f"SELECT * FROM {t}"))
    assert not any(n in blob for n in names), [n for n in names if n in blob]
    before = ev.evaluate(c); wb = ev.web_report(c)
    a = TestClient(create_app(db, KEYS))
    assert a.post("/demo/real-claim", json={}, headers=H("k-sync")).status_code == 201     # demo vendor + item now exist in the LIVE db
    c2 = connect(db)
    assert c2.execute("SELECT COUNT(*) n FROM vendors WHERE vendor_id='DEMO-R1'").fetchone()["n"] == 1
    after = ev.evaluate(c2)
    assert after["dev"]["items"] == before["dev"]["items"] and after["holdout"]["items"] == before["holdout"]["items"]
    assert after["views"]["all"]["n"] == 300 and ev.web_report(c2)["items"] == wb["items"] == 300
    vs = {v["vendor_id"]: v for v in a.get("/vendors", headers=H("k-agent")).json()}
    assert vs["DEMO-R1"]["demo"] is True and not any(v["demo"] for k, v in vs.items() if k != "DEMO-R1")


def test_demo_file_still_refused_by_the_seed_loader():
    with pytest.raises(ValueError, match="demo-only"):
        seed.load_vendors(None, "data/v2/demo_real_vendors.json")
