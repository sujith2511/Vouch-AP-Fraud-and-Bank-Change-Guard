import collections, json, re, sys
sys.path.insert(0, "scripts")
from dedupe_vendors import stale, base_of

V = json.load(open("data/vendors.json"))

def _unique(vals): return [k for k, n in collections.Counter(vals).items() if n > 1] == []

def test_vendor_identity_fields_are_unique():
    assert _unique(v["legal_name"].lower() for v in V) and _unique(base_of(v["legal_name"]).lower() for v in V)
    assert _unique(v["domain"] for v in V) and _unique(v["contact_name"] for v in V) and _unique(v["phone"] for v in V)

def test_lookalikes_unique_fresh_and_never_a_real_domain():
    allk = [l["domain"] for v in V for l in v["lookalikes"]]
    assert _unique(allk) and not set(allk) & {v["domain"] for v in V}
    assert not any(stale(v) for v in V)

def test_only_reserved_tlds_and_fake_banks():
    for v in V:
        assert re.search(r"\.(example)$", v["domain"]) and all(re.search(r"\.(example|test|invalid)$", l["domain"]) for l in v["lookalikes"])
        assert v["bank"]["account"].startswith("TEST") and v["phone"].startswith("(415) 555-01")
