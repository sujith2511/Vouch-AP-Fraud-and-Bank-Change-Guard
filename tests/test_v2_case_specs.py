import collections, json, subprocess, sys, hashlib

S = json.load(open("data/v2/case_specs.json"))
V = {v["vendor_id"]: v for v in json.load(open("data/v2/vendors.v2.json"))}

def test_300_specs_and_minimum_per_scenario_in_both_splits():
    assert len(S) == 300
    by = collections.defaultdict(collections.Counter)
    for s in S: by[s["scenario"]][s["split"]] += 1
    assert len(by) == 31
    for k, c in by.items(): assert sum(c.values()) >= 8 and c["dev"] >= 2 and c["holdout"] >= 2, (k, c)

def test_split_is_by_vendor_and_pairs_stay_together():
    for s in S: assert V[s["vendor_id"]]["split"] == s["split"]
    vs = collections.defaultdict(set)
    for s in S: vs[s["vendor_id"]].add(s["split"])
    assert all(len(x) == 1 for x in vs.values())
    pairs = collections.defaultdict(list)
    for s in S:
        if s.get("pair_id"): pairs[s["pair_id"]].append(s)
    assert pairs and all(len(p) == 2 and p[0]["vendor_id"] == p[1]["vendor_id"] for p in pairs.values())

def test_hard_share_and_hard_definition():
    assert sum(s["difficulty"] == "hard" for s in S) / 300 >= 0.35
    for s in S:
        if s["label"] == "legit" and s["difficulty"] == "hard": assert s["surface_features"], s["id"]
        if s["label"] == "fraud": assert s["tells"], s["id"]

def test_auto_clear_cases_satisfy_the_policy_rules_and_no_fraud_expects_auto_clear():
    for s in S:
        if s["label"] == "fraud": assert s["lane"] != "auto_clear"
        if s["lane"] == "auto_clear":
            v = V[s["vendor_id"]]; a = s["auth"]
            assert not s["claim_changes_bank"] and all(a[k] == "pass" for k in ("spf", "dkim", "dmarc"))
            assert s["from_addr"].split("@")[1] == v["domain"] and s["reply_to"].split("@")[1] == v["domain"]
            assert 0 < s["invoice"]["amount"] <= 1.5 * v["typical_amount"]

def test_reserved_domains_and_fake_banks_only():
    for s in S:
        for addr in [s["from_addr"], s["reply_to"], s["to"]] + s["cc"]: assert addr.split("@")[1].endswith((".example", ".test", ".invalid")), addr
        b = s["claimed_bank"]
        if b: assert b["routing_or_iban"].startswith(("999", "99999", "DE00ZZBK", "GB00ZZBK", "FR00ZZBK")) and "test" not in json.dumps(b).lower()

def test_attribute_vectors_unique():
    vec = [(s["scenario"], s["difficulty"], s["attrs"]["channel"], s["attrs"]["thread"], s["attrs"]["length"], s["attrs"]["register"], s["attrs"]["device_footer"], s["attrs"]["language"],
            tuple(a["type"] for a in s["attachments"]), s["attrs"]["urgency"], tuple(s["attrs"]["noise"]), s["sub_variant"]) for s in S]
    assert len(set(vec)) == len(vec)

def test_injection_cases_use_injections_json_ids():
    inj = {p["id"]: p for p in json.load(open("data/injections.json"))["payloads"]}
    cases = [s for s in S if s["injection"]]
    assert len(cases) >= 8 and {c["injection"]["hidden_in"] for c in cases} == {"html_comment", "white_span", "quoted_reply", "footer", "attachment_text"}
    assert all(inj[c["injection"]["payload_id"]]["text"] == c["injection"]["text"] for c in cases)

def test_case_spec_build_is_deterministic():
    h = lambda: hashlib.sha256(open("data/v2/case_specs.json", "rb").read()).hexdigest()
    before = h(); subprocess.run([sys.executable, "-I", "scripts/v2/case_specs.py"], check=True, capture_output=True)
    assert h() == before
