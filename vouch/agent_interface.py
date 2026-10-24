"""What the real agent (Sujith) calls, plus a trivial rule-based stub so the pipeline runs end to end.

The agent can ONLY propose or ask. Both calls go through the same rulebook as everything else; an agent that tries anything
else gets Denied (and the attempt, with its stated reason, is audited). Two interchangeable clients:
  LocalClient(db_path)        in-process (tests, eval)
  HttpClient(base_url, key)   against the deployed API with the agent's API key
"""
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol

from . import core, tools_data
from .db import connect


@dataclass
class AgentDecision:
    """kind='propose' -> verdict in {'legit','fraud','uncertain'}; kind='ask' -> question for a human (item goes to NEEDS_INFO).
    The state machine is NEW -> PROPOSED -> NEEDS_INFO, so run_agent() records an 'uncertain' proposal before the question."""
    kind: str
    verdict: Optional[str] = None
    confidence: Optional[float] = None
    reasons: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    question: Optional[str] = None


class Agent(Protocol):
    def investigate(self, item: dict, client) -> AgentDecision: ...


class LocalClient:
    def __init__(self, db_path, actor_id="agent"):
        self.conn, self.actor_id = connect(db_path), actor_id

    def get_item(self, item_id):
        from .api import public_item
        return public_item(core.load_item(self.conn, item_id))

    def list_items(self, state=None):
        from .api import public_item
        return [public_item(i) for i in core.list_items(self.conn, state)]

    # read-only tools Sujith's agent wraps (same names as the tool list in the team plan)
    def read_vendor_history(self, vendor_id, limit=50): return tools_data.read_vendor_history(self.conn, vendor_id, limit)
    def compare_amounts(self, vendor_id, amount): return tools_data.compare_amounts(self.conn, vendor_id, amount)
    def check_domain(self, vendor_id, sender): return tools_data.check_domain(self.conn, vendor_id, sender)

    def read_email_history(self, vendor_id, limit=25): return tools_data.read_email_history(self.conn, vendor_id, limit)

    def propose(self, item_id, verdict, confidence=None, reasons=(), evidence=None):
        return core.propose(self.conn, item_id, verdict, confidence, reasons, evidence, self.actor_id)

    def ask(self, item_id, question, reasons=(), evidence=None):
        return core.ask(self.conn, item_id, question, reasons, evidence, self.actor_id)


class HttpClient:
    def __init__(self, base_url, api_key):
        import httpx
        self.h = httpx.Client(base_url=base_url, headers={"X-API-Key": api_key}, timeout=30)

    def _ok(self, r):
        r.raise_for_status(); return r.json()

    def get_item(self, item_id): return self._ok(self.h.get(f"/items/{item_id}"))
    def list_items(self, state=None): return self._ok(self.h.get("/items", params={"state": state} if state else {}))
    def read_vendor_history(self, vendor_id, limit=50): return self._ok(self.h.get(f"/vendors/{vendor_id}", params={"limit": limit}))
    def compare_amounts(self, vendor_id, amount): return self._ok(self.h.get(f"/vendors/{vendor_id}/compare_amounts", params={"amount": amount}))
    def check_domain(self, vendor_id, sender): return self._ok(self.h.get(f"/vendors/{vendor_id}/check_domain", params={"sender": sender}))
    def read_email_history(self, vendor_id, limit=25): return self._ok(self.h.get(f"/vendors/{vendor_id}/email_history", params={"limit": limit}))

    def propose(self, item_id, verdict, confidence=None, reasons=(), evidence=None):
        return self._ok(self.h.post(f"/items/{item_id}/propose", json={"verdict": verdict, "confidence": confidence, "reasons": list(reasons), "evidence": evidence}))

    def ask(self, item_id, question, reasons=(), evidence=None):
        return self._ok(self.h.post(f"/items/{item_id}/ask", json={"question": question, "reasons": list(reasons), "evidence": evidence}))


def run_agent(agent, client, item_id):
    """Fetch the item, let the agent investigate, submit its decision. Returns the updated item."""
    item = client.get_item(item_id)
    d = agent.investigate(item, client)
    if d.kind == "ask":
        if item["state"] == "NEW":   # no skipped states: a question is only legal from PROPOSED, so record an 'uncertain' proposal first
            client.propose(item_id, "uncertain", d.confidence, d.reasons, d.evidence)
        return client.ask(item_id, d.question, d.reasons, d.evidence)
    return client.propose(item_id, d.verdict, d.confidence, d.reasons, d.evidence)


INJECTION = re.compile(r"ignore (all )?(previous|prior|above)|approve (this|the|payment)|mark (it |this )?as approved|skip (the )?(call|verif)|assistant (note|instruction)|system notice|call (the )?post", re.I)


class RuleBasedAgent:
    """Deliberately simple stand-in. It reads the email text only to FLAG suspicion; it can never approve anything."""

    def investigate(self, item, client):
        e, claim, v = item["email"], item["claim"], item["vendor"]
        ev, why = [], []
        dom = client.check_domain(item["vendor_id"], e["from"]) if hasattr(client, "check_domain") else None
        amt = client.compare_amounts(item["vendor_id"], claim["amount"]) if hasattr(client, "compare_amounts") else None
        ev.append({"tool": "check_domain", "result": dom}); ev.append({"tool": "compare_amounts", "result": amt})
        auth_bad = [k for k in ("spf", "dkim", "dmarc") if (e.get("auth") or {}).get(k) != "pass"]
        off = dom and not dom["exact_match"]
        reply_off = bool(e.get("reply_to")) and e["reply_to"].split("@")[-1].lower().rstrip(">") != v["domain"].lower()
        if INJECTION.search(e.get("body", "") + " " + e.get("subject", "")):
            why.append("email contains text addressed to an AI/system (possible prompt injection)")
        if off: why.append(f"sender domain {dom['sender_domain']} != {v['domain']}")
        if auth_bad: why.append("auth failed: " + ",".join(auth_bad))
        if reply_off: why.append("reply-to differs from vendor domain")
        if why:
            return AgentDecision("propose", "fraud", 0.9, why, ev)
        if item.get("is_bank_change"):
            return AgentDecision("propose", "uncertain", 0.5, ["claims a bank change; needs human verification"], ev)
        if amt and not amt["within_1_5x"]:
            return AgentDecision("ask", reasons=["amount above 1.5x typical"], evidence=ev,
                                 question=f"Amount ${claim['amount']:,.2f} is {amt['ratio_to_typical']:.1f}x typical. Is there a PO or change order?")
        return AgentDecision("propose", "legit", 0.8, ["domain, auth and amount look normal"], ev)
