"""Load emails into items, run any agent through the pipeline, apply the policy lane.
    python -m vouch.run_pipeline --emails data/emails.jsonl --db run.db [--agent stub]
A custom agent: --agent mypkg.mymodule:MyAgent (class with investigate(item, client) -> AgentDecision)."""
import argparse, importlib, os, time

from . import core, seed
from .agent_interface import LocalClient, RuleBasedAgent, run_agent
from .db import connect, init_db


def load_agent(spec):
    if spec in (None, "stub"):
        return RuleBasedAgent()
    mod, _, cls = spec.partition(":")
    return getattr(importlib.import_module(mod), cls)()


def run(db_path, emails_path, vendors_path="data/vendors.json", agent=None, limit=None, fresh=True):
    agent = agent or RuleBasedAgent()
    if fresh and os.path.exists(db_path):
        for suf in ("", "-wal", "-shm"):
            if os.path.exists(db_path + suf): os.remove(db_path + suf)
    init_db(db_path).close()
    c = connect(db_path)
    seed.load_vendors(c, vendors_path)
    n = seed.ingest_emails(c, emails_path, limit)
    client, stats = LocalClient(db_path), {"items": n, "agent_errors": 0, "lanes": {}}
    for it in core.list_items(c, "NEW", limit=100000):
        try:
            run_agent(agent, client, it["id"])
        except Exception as e:     # an agent crash must not stop the run or bypass the rulebook; the item stays NEW
            stats["agent_errors"] += 1
            core.record_denied(c, actor="agent", action="propose", item_id=it["id"], reason=repr(e)[:300], code="AGENT_ERROR", state="NEW", vendor_id=it["vendor_id"])
            continue
        lane = core.apply_policy(c, it["id"])
        stats["lanes"][lane] = stats["lanes"].get(lane, 0) + 1
    return c, stats


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--emails", default="data/emails.jsonl"); ap.add_argument("--db", default="run.db")
    ap.add_argument("--vendors", default="data/vendors.json"); ap.add_argument("--agent", default="stub"); ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    if not os.path.exists(a.emails):
        raise SystemExit(f"{a.emails} not found (generate it with scripts/generate_emails.py, or use data/fixtures/emails_fixture.jsonl)")
    t = time.time(); c, stats = run(a.db, a.emails, a.vendors, load_agent(a.agent), a.limit)
    print(stats, f"{time.time() - t:.1f}s -> {a.db}")


if __name__ == "__main__":
    main()
