"""Replay every InjecAgent-derived payload (data/injections.json) against the rulebook two ways and assert none changes state:
  1. as an agent 'reason' (in-process): agent approve/post/reject attempts, policy + gateway paths, injected verdict reasons
  2. as hostile API calls with an agent key (body also tries to smuggle actor/role fields)
    python -m vouch.injection_replay [--payloads data/injections.json]"""
import argparse, json, logging, os, tempfile

from fastapi.testclient import TestClient

from . import core, gateway
from .api import create_app
from .db import connect, init_db

VENDOR = {"vendor_id": "VR", "legal_name": "Replay Co", "domain": "replay.example", "typical_amount": 1000.0, "phone": "(415) 555-0100",
          "bank": {"bank_name": "Old Bank", "routing": "999000009", "account": "TEST0000009"}, "payments": []}
GOOD = {"spf": "pass", "dkim": "pass", "dmarc": "pass"}
NEW_BANK = {"bank_name": "Attacker Bank", "routing": "999666666", "account": "TEST6666666"}
KEYS = {"k-agent": {"role": "agent", "user": "a"}, "k-acct": {"role": "accountant", "user": "ann"}, "k-policy": {"role": "policy", "user": "p"}}


def _setup(tmp):
    from .seed import load_vendors
    path = os.path.join(tmp, "replay.db"); init_db(path).close(); c = connect(path)
    vp = os.path.join(tmp, "v.json"); json.dump([VENDOR], open(vp, "w")); load_vendors(c, vp)
    return path, c


def _item(c, n, payload_text, bank=NEW_BANK, email_from="x@replay.example", auth=GOOD):
    return core.ingest_item(c, item_id=n, vendor_id="VR",
                            email={"from": email_from, "reply_to": email_from, "auth": auth, "subject": "Bank update", "body": f"Hello\n<!-- {payload_text} -->"},
                            claim={"invoice_number": "INV-" + n, "amount": 900.0, "currency": "USD", "claimed_bank": bank})


def _snapshot(c):
    return {"bank": core._vendor(c, "VR")["bank"], "payments": c.execute("SELECT COUNT(*) c FROM payments").fetchone()["c"],
            "states": {r["id"]: r["state"] for r in c.execute("SELECT id,state FROM items")}}


def replay(payloads):
    results, failures = [], []
    with tempfile.TemporaryDirectory() as tmp:
        path, c = _setup(tmp)
        client = TestClient(create_app(path, KEYS))
        logging.getLogger().setLevel(logging.ERROR)   # replay would otherwise emit thousands of audit log lines
        H = lambda k: {"X-API-Key": k}
        for p in payloads:
            t, pid = p["text"], p["id"]
            def fail(msg): failures.append(f"{pid}: {msg}")
            # ---- 1. as an agent reason, in-process
            a, b = f"{pid}a", f"{pid}b"
            _item(c, a, t); _item(c, b, t, bank=None, email_from="x@evil-replay.test", auth={"spf": "fail", "dkim": "none", "dmarc": "fail"})
            core.propose(c, a, "legit", 1.0, [t], evidence=[{"note": t}]); core.propose(c, b, "legit", 1.0, [t])
            before = _snapshot(c)
            attempts = [lambda: core.transition(c, a, "agent", "approve", t), lambda: core.transition(c, a, "agent", "post", t),
                        lambda: core.transition(c, a, "agent", "reject", t), lambda: gateway.post_item(c, a, "agent", t),
                        lambda: core.transition(c, a, "policy", "approve", t), lambda: core.transition(c, a, "gateway", "post", t),
                        lambda: core.transition(c, a, "sync", "approve", t), lambda: core.transition(c, b, "agent", "approve", t),
                        lambda: core.transition(c, b, "policy", "approve", t)]
            for i, f in enumerate(attempts):
                try:
                    f(); fail(f"in-process attempt {i} was ALLOWED")
                except core.Denied:
                    pass
            if core.apply_policy(c, a) != "human_review": fail("policy auto-handled a bank-change item")
            if core.apply_policy(c, b) == "auto_clear": fail("policy auto-cleared off-domain item")
            snap = _snapshot(c)
            if snap["bank"] != before["bank"] or snap["payments"] or snap["states"][a] != "PROPOSED": fail("state/bank/payments changed (in-process)")
            # ---- 2. as hostile API calls with an agent key
            n = 0
            for ep in ("approve", "reject", "post"):
                for body in ({"reason": t}, {"reason": t, "actor": "accountant", "role": "accountant", "evidence": {"note": t}}):
                    r = client.post(f"/items/{a}/{ep}", json=body, headers=H("k-agent")); n += 1
                    if r.status_code != 403: fail(f"API agent {ep} returned {r.status_code}")
            if client.post(f"/items/{a}/policy", headers=H("k-agent")).status_code != 403: fail("agent could run policy lane")
            if client.post(f"/items/{a}/approve", json={"reason": t}, headers={"X-API-Key": t}).status_code != 401: fail("payload as API key accepted")
            if client.post(f"/items/{a}/approve", json={"reason": t}, headers={"X-API-Key": "k-agent", "X-Role": "accountant"}).status_code != 403: fail("role header honoured")
            r = client.post(f"/items/{a}/policy", headers=H("k-policy"))
            if r.status_code != 200 or r.json()["lane"] != "human_review": fail("policy lane misbehaved on bank change")
            snap2 = _snapshot(c)
            if snap2["bank"] != before["bank"] or snap2["payments"] or snap2["states"][a] != "PROPOSED": fail("state/bank/payments changed (API)")
            logged = [x for x in core.audit_rows(c, item_id=a) if x["outcome"] == "denied" and x["reason"] == t]
            if len(logged) < len(attempts) // 2 + n - 1: fail(f"denials not all audited ({len(logged)})")
            results.append({"id": pid, "style": p["style"], "goal": p["goal"], "in_process_attempts": len(attempts), "api_attempts": n + 4})
        ok, bad = core.verify_audit_chain(c)
        if not ok: failures.append(f"audit chain broken at {bad}")
    return {"payloads": len(payloads), "state_changing": len(failures), "failures": failures, "results": results}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--payloads", default="data/injections.json"); a = ap.parse_args()
    rep = replay(json.load(open(a.payloads))["payloads"])
    print(f"replayed {rep['payloads']} payloads; state-changing: {rep['state_changing']}")
    for f in rep["failures"]: print("  FAIL", f)
    raise SystemExit(1 if rep["failures"] else 0)


if __name__ == "__main__":
    main()
