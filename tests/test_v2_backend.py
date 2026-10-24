import json, os, re, pytest
from fastapi.testclient import TestClient
from vouch import core, eval as ev, run_pipeline, seed
from vouch.agent_interface import AgentDecision, LocalClient, HttpClient
from vouch.api import create_app
from vouch.db import connect

KEYS = {"k-sync": {"role": "sync", "user": "s"}, "k-agent": {"role": "agent", "user": "a1"}, "k-ann": {"role": "accountant", "user": "ann"},
        "k-policy": {"role": "policy", "user": "p"}, "k-gw": {"role": "gateway", "user": "g"}}
H = lambda k: {"X-API-Key": k}
V2 = "data/v2/emails.jsonl"
FORBIDDEN_KEYS = {"truth", "provenance", "expected_lane", "correct_agent_verdict", "hard_reason", "tells", "surface_features", "callback_outcome", "lookalike_fuzzer", "pair_id", "pair_with", "family", "sub_variant"}


def v2_records():
    return [json.loads(l) for l in open(V2) if l.strip()]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    db = str(tmp_path_factory.mktemp("v2") / "v2.db")
    c, stats = run_pipeline.run(db, dataset="v2")
    return db, c, stats


def walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield "key", k
            yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)
    elif isinstance(o, str):
        yield "val", o


def test_v1_default_unchanged(tmp_path):
    assert seed.dataset_version() == "v1"
    c, stats = run_pipeline.run(str(tmp_path / "v1.db"), "data/fixtures/emails_fixture.jsonl")
    assert stats["items"] > 0 and not os.path.exists(str(tmp_path / "v1.db") + ".evalkey")


def test_v2_loads_all_300_with_phantoms_as_unknown_vendor(run):
    db, c, stats = run
    assert stats["items"] == 300 and stats["agent_errors"] == 0 and sum(stats["lanes"].values()) == 300
    phantoms = {r["id"] for r in v2_records() if not seed.json.load(open("data/v2/vendors.v2.json")) is None and r["vendor_id"].startswith("PH")}
    assert phantoms
    unknown = {r["id"] for r in c.execute("SELECT id FROM items WHERE vendor_id='UNKNOWN'")}
    assert unknown == phantoms
    assert not c.execute("SELECT 1 FROM vendors WHERE vendor_id LIKE 'PH%'").fetchone()
    assert c.execute("SELECT COUNT(*) n FROM email_history").fetchone()["n"] == 817
    assert core.verify_audit_chain(c) == (True, None)


def test_split_kept_on_each_email_and_only_in_evalkey(run):
    db, c, _ = run
    import sqlite3
    k = sqlite3.connect(db + ".evalkey")
    got = dict(k.execute("SELECT item_id, split FROM truth"))
    assert got == {r["id"]: r["split"] for r in v2_records()}
    assert {"dev", "holdout"} == set(got.values())
    assert c.execute("SELECT COUNT(*) n FROM truth").fetchone()["n"] == 0


def test_demo_real_vendors_still_refused():
    from vouch.db import init_db
    with pytest.raises(ValueError):
        seed.load_vendors_v2(connect(":memory:") if False else None, vendors_path="data/v2/demo_real_vendors.json")


def test_no_truth_or_provenance_in_any_agent_facing_output(run):
    db, c, _ = run
    recs = {r["id"]: r for r in v2_records()}
    pick = {}
    for r in recs.values():
        pick.setdefault(r["truth"]["scenario"], r["id"])
    ids = [pick[s] for s in ("thread_hijack", "prompt_injection", "legit_bank_change_callback", "phantom_vendor", "lookalike_domain", "routine") if s in pick]
    ids += [r["id"] for r in recs.values() if r["truth"]["injection"]][:4]
    secrets = set()
    for i in ids:
        t = recs[i]["truth"]
        secrets |= {t["scenario"], t["sub_variant"], t["hard_reason"], t["pair_id"]}
        secrets |= {x["id"] for x in t["tells"]} | set(t["surface_features"] or [])
        if t["injection"]: secrets |= {t["injection"]["source_id"], t["injection"]["goal"], t["injection"]["payload_id"]}
        secrets |= {recs[i]["provenance"]["generator"], recs[i]["provenance"]["style_sources"]}
    secrets = {s for s in secrets if isinstance(s, str) and ("_" in s or len(s) >= 12)}   # identifiers/phrases, not common words
    outputs = []
    api = TestClient(create_app(db, KEYS))
    for i in ids:
        vid = c.execute("SELECT vendor_id FROM items WHERE id=?", (i,)).fetchone()["vendor_id"]
        for role in ("k-agent", "k-ann", "k-sync", "k-policy", "k-gw"):
            for url in (f"/items/{i}", f"/items/{i}/audit", f"/vendors/{vid}", f"/vendors/{vid}/why", f"/vendors/{vid}/email_history",
                        f"/vendors/{vid}/check_domain?sender=x@y.example", f"/vendors/{vid}/compare_amounts?amount=100"):
                r = api.get(url, headers=H(role)); assert r.status_code == 200, (url, r.text); outputs.append(r.json())
    for role in ("k-agent", "k-ann"):
        for url in ("/items", "/audit", "/vendors", "/audit/verify"):
            r = api.get(url, headers=H(role)); assert r.status_code == 200; outputs.append(r.json())
    lc = LocalClient(db)
    for i in ids:
        item = lc.get_item(i); vid = item["vendor_id"]
        outputs += [item, lc.read_vendor_history(vid), lc.read_email_history(vid), lc.compare_amounts(vid, 100.0), lc.check_domain(vid, item["email"]["from"])]
    outputs += lc.list_items("NEW") + lc.list_items("PROPOSED")
    assert len(outputs) > 100
    for o in outputs:
        for kind, x in walk(o):
            if kind == "key": assert x not in FORBIDDEN_KEYS, f"forbidden key {x!r}"
            else:
                for s in secrets: assert s not in x, f"truth value leaked: {s!r}"
    blob = json.dumps(outputs)
    assert not re.search(r'"PH\d{3}"', blob), "dataset phantom vendor id reached an agent-facing output"
    raw = open(db, "rb").read() + (open(db + "-wal", "rb").read() if os.path.exists(db + "-wal") else b"")
    for needle in (b"hard_reason", b"correct_agent_verdict", b"provenance"):
        assert needle not in raw, f"{needle!r} stored in the agent-readable DB"


def test_httpclient_has_same_tools_as_localclient():
    for name in ("get_item", "list_items", "read_vendor_history", "compare_amounts", "check_domain", "read_email_history", "propose", "ask"):
        assert hasattr(LocalClient, name) and hasattr(HttpClient, name), name


def test_new_tool_endpoints_and_role_rules(run):
    db, c, _ = run
    api = TestClient(create_app(db, KEYS))
    v = api.get("/vendors", headers=H("k-agent")).json()
    reg = next(x for x in v if x["registered"])
    assert api.get(f"/vendors/{reg['vendor_id']}/check_domain?sender=a@{reg['domain']}", headers=H("k-agent")).status_code == 200
    assert api.get(f"/vendors/{reg['vendor_id']}/compare_amounts?amount=10", headers=H("k-ann")).json()
    for url in (f"/vendors/{reg['vendor_id']}/check_domain?sender=a@b.example", f"/vendors/{reg['vendor_id']}/compare_amounts?amount=10"):
        assert api.get(url).status_code == 401 and api.get(url, headers=H("bad")).status_code == 401
    assert api.get("/vendors/NOPE/check_domain?sender=a@b.example", headers=H("k-agent")).status_code == 404
    assert api.get("/vendors/NOPE/compare_amounts?amount=1", headers=H("k-agent")).status_code == 404
    assert api.get("/vendors").status_code == 401
    assert api.get("/health").json() == {"ok": True}


def test_vendors_list_basic_fields_masked_and_no_truth(run):
    db, c, _ = run
    api = TestClient(create_app(db, KEYS))
    v = api.get("/vendors", headers=H("k-agent")).json()
    assert len(v) == 61 and sum(not x["registered"] for x in v) == 1
    row = next(x for x in v if x["registered"])
    assert {"vendor_id", "name", "domain", "typical_amount", "bank", "items"} <= set(row)
    full = json.dumps(c.execute("SELECT bank_account FROM vendors WHERE vendor_id=?", (row["vendor_id"],)).fetchone()["bank_account"])
    assert full.strip('"') not in json.dumps(v)


def test_cors_origins_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://ui.example")
    api = TestClient(create_app(str(tmp_path / "c.db"), KEYS))
    r = api.options("/vendors", headers={"Origin": "https://ui.example", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "https://ui.example"
    r = api.options("/vendors", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers


def test_demo_inject_goes_through_pipeline_and_cannot_post(run, monkeypatch, tmp_path):
    monkeypatch.delenv("VOUCH_ENV", raising=False)
    db = str(tmp_path / "d.db")
    c, _ = run_pipeline.run(db, dataset="v2", limit=5)
    api = TestClient(create_app(db, KEYS))
    assert api.post("/demo/inject", headers=H("k-agent")).status_code == 403
    r = api.post("/demo/inject", headers=H("k-sync")); assert r.status_code == 201, r.text
    body = r.json(); item = body["item"]
    assert body["lane"] in ("human_review", "reject") and item["state"] in ("PROPOSED", "REJECTED")
    assert "Ignore all previous instructions" in item["email"]["body"] and item["id"].startswith("DEMO-")
    assert core.verify_audit_chain(connect(db)) == (True, None)
    assert connect(db).execute("SELECT COUNT(*) n FROM payments").fetchone()["n"] == 0
    # the second call must not collide
    assert api.post("/demo/inject", headers=H("k-sync")).status_code == 201


def test_demo_inject_disabled_in_prod_unless_flag(tmp_path, monkeypatch):
    db = str(tmp_path / "p.db")
    run_pipeline.run(db, dataset="v2", limit=2)
    monkeypatch.setenv("VOUCH_ENV", "prod")
    api = TestClient(create_app(db, KEYS))
    assert api.post("/demo/inject", headers=H("k-sync")).status_code == 404
    monkeypatch.setenv("DEMO_ENDPOINTS", "1")
    assert api.post("/demo/inject", headers=H("k-sync")).status_code == 201


def test_eval_reports_verdict_accuracy_and_views(run):
    db, c, _ = run
    rep = ev.evaluate(c)
    assert rep["dev"]["items"] + rep["holdout"]["items"] == 300 and rep["holdout"]["items"] == 108
    for sp in ("dev", "holdout"): assert 0 <= rep[sp]["verdict_accuracy"] <= 1 and 0 <= rep[sp]["lane_accuracy"] <= 1
    assert rep["views"]["hard"]["n"] == 127 and rep["views"]["fraud_no_bank_change"]["n"] == 57
    assert "dev" in ev.table(rep) and "fraud_no_bank_change" in ev.table(rep)


def test_code_cannot_be_fooled_on_all_15_injection_cases():
    r = ev.injection_resistance()
    assert r["injection_cases"] == 15 and r["passed"], r["failures"]
    assert r["attacks_denied"] == r["attack_attempts"] and r["payments_posted"] == 0
