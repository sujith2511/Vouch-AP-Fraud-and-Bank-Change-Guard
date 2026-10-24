"""Load emails into items, run any agent through the pipeline, apply the policy lane.
    python -m vouch.run_pipeline --emails data/emails.jsonl --db run.db [--agent stub]
A custom agent: --agent mypkg.mymodule:MyAgent (class with investigate(item, client) -> AgentDecision)."""
import argparse, importlib, os, time

from . import core, seed
from .agent_interface import LocalClient, RuleBasedAgent, run_agent
from .db import connect, init_db


def load_agent(spec, web=None):
    """web='sim': the agent's web check looks fictional vendors up in the SIMULATED directory (vouch/web_sim.py). Default off."""
    if spec in (None, "stub"):
        if web == "sim":
            raise SystemExit("--web sim needs an LLM-based agent (e.g. --agent vouch.llm_agent:LLMAgent); the rule-based agent has no web check")
        return RuleBasedAgent()
    mod, _, cls = spec.partition(":")
    klass = getattr(importlib.import_module(mod), cls)
    if web == "sim":
        from .llm_agent import LLMAgent
        from .web_sim import with_simulated_web
        if not issubclass(klass, LLMAgent):
            raise SystemExit("--web sim needs an LLMAgent subclass")
        klass = with_simulated_web(klass)
    return klass()


def run(db_path, emails_path=None, vendors_path="data/vendors.json", agent=None, limit=None, fresh=True, dataset=None, which="emails"):
    """dataset: 'v1' (default; or env VOUCH_DATASET) or 'v2'. For v2, emails_path overrides the file chosen by `which` (emails|dev|holdout)."""
    agent = agent or RuleBasedAgent()
    if fresh:
        for suf in ("", "-wal", "-shm", ".evalkey"):
            if os.path.exists(db_path + suf): os.remove(db_path + suf)
    init_db(db_path).close()
    c = connect(db_path)
    if seed.dataset_version(dataset) == "v2":
        seed.load_vendors_v2(c)
        n = seed.ingest_emails_v2(c, db_path, which, limit, emails_path=emails_path)
    else:
        seed.load_vendors(c, vendors_path)
        n = seed.ingest_emails(c, emails_path or "data/emails.jsonl", limit)
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
    ap = argparse.ArgumentParser(); ap.add_argument("--emails", default=None); ap.add_argument("--dataset", default=None, help="v1 (default) or v2; env VOUCH_DATASET")
    ap.add_argument("--which", default="emails", choices=["emails", "dev", "holdout"], help="v2 only")
    ap.add_argument("--web", default=None, choices=["sim"], help="sim: simulated web lookups for fictional vendors (LLM agents only; default off)"); ap.add_argument("--db", default="run.db")
    ap.add_argument("--vendors", default="data/vendors.json"); ap.add_argument("--agent", default="stub"); ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    if a.emails and not os.path.exists(a.emails):
        raise SystemExit(f"{a.emails} not found (v1: data/fixtures/emails_fixture.jsonl; v2: data/v2/emails.jsonl)")
    t = time.time(); c, stats = run(a.db, a.emails, a.vendors, load_agent(a.agent, a.web), a.limit, dataset=a.dataset, which=a.which)
    print(stats, f"{time.time() - t:.1f}s -> {a.db}")


if __name__ == "__main__":
    main()
