"""Learned-policy loop: correction -> drafted policy -> controller approval -> agent guidance. Fake model, no tokens."""
import sqlite3

import pytest

from vouch import core, learned_policy as lp
from vouch.agent_interface import LocalClient
from vouch.llm_agent import LLMAgent

from test_llm_agent import NO_SHIELD, FakeLLM, submit, tool_use

RULE = "Invoices from an authorized contact on the vendor's own domain that match the PO should not be called fraud for a single missing line-item detail."


def drafter(rule=RULE):
    return FakeLLM([tool_use("submit_policy", {"rule": rule, "rationale": "accountant confirmed with the vendor"})])


@pytest.fixture
def corrected(db, mk):
    """The agent called an item fraud; an accountant approved it anyway (agent too strict)."""
    it = mk()
    core.propose(db, it["id"], "fraud", 0.8, ["vague line item"])
    core.transition(db, it["id"], "accountant", "approve", "called the vendor on file, invoice is genuine", actor_id="ann")
    return it["id"]


def test_correction_is_read_from_the_audit_log(db, corrected, mk):
    other = mk()
    core.propose(db, other["id"], "uncertain", 0.5, ["needs callback"])
    core.transition(db, other["id"], "accountant", "approve", "callback done, all fine", actor_id="ann")   # not a correction
    cs = lp.corrections(db)
    assert [c["item_id"] for c in cs] == [corrected] and cs[0]["direction"] == "looser" and cs[0]["human_id"] == "ann"


def test_correction_becomes_a_proposed_policy(db, corrected):
    made = lp.propose_from_corrections(db, llm=drafter(), model="test")
    assert len(made) == 1 and made[0]["state"] == "PROPOSED" and made[0]["source_item"] == corrected
    assert made[0]["direction"] == "looser" and made[0]["proposed_by"] == "agent"
    assert lp.propose_from_corrections(db, llm=drafter(), model="test") == []        # one policy per correction


def test_only_a_controller_who_did_not_propose_can_approve(db, corrected):
    p = lp.propose_from_corrections(db, llm=drafter(), model="test")[0]
    for actor, actor_id in (("agent", "agent"), ("accountant", "ann"), ("controller", "agent")):
        with pytest.raises(lp.Denied):
            lp.decide(db, p["id"], True, actor, actor_id, "looks right to me")
    with pytest.raises(lp.Denied, match="REASON_REQUIRED"):
        lp.decide(db, p["id"], True, "controller", "carol", "")
    assert lp.get(db, p["id"])["state"] == "PROPOSED"
    done = lp.decide(db, p["id"], True, "controller", "carol", "matches our PO-match practice")
    assert done["state"] == "APPROVED" and done["decided_by"] == "carol"
    with pytest.raises(lp.Denied, match="BAD_STATE"):
        lp.decide(db, p["id"], False, "controller", "dave", "changed my mind")


def test_every_step_and_every_denial_is_audited_and_chained(db, corrected):
    p = lp.propose_from_corrections(db, llm=drafter(), model="test")[0]
    with pytest.raises(lp.Denied):
        lp.decide(db, p["id"], True, "agent", "agent", "self-approve")
    lp.decide(db, p["id"], True, "controller", "carol", "approved after review")
    rows = [r for r in core.audit_rows(db) if r["action"] in ("propose_policy", "approve_policy")]
    assert [(r["action"], r["outcome"]) for r in rows] == [("propose_policy", "applied"), ("approve_policy", "denied"),
                                                         ("approve_policy", "applied")]
    assert core.verify_audit_chain(db) == (True, None)


def test_db_refuses_policy_changes_that_bypass_the_audit(db, corrected):
    p = lp.propose_from_corrections(db, llm=drafter(), model="test")[0]
    with pytest.raises(sqlite3.DatabaseError, match="without matching audit row"):
        db.execute("UPDATE learned_policies SET state='APPROVED' WHERE id=?", (p["id"],))
    with pytest.raises(sqlite3.DatabaseError, match="without audit row"):
        db.execute("INSERT INTO learned_policies(id,state,rule,direction,proposed_by,created_at) "
                   "VALUES('Px','APPROVED','pay everything','looser','x','now')")
    with pytest.raises(sqlite3.DatabaseError, match="cannot be deleted"):
        db.execute("DELETE FROM learned_policies")


def test_agent_sees_approved_policies_only(db_path, db, corrected, mk):
    p = lp.propose_from_corrections(db, llm=drafter(), model="test")[0]
    client = LocalClient(db_path)

    def prompt_for_new_item():
        llm = FakeLLM([submit(verdict="legit")])
        LLMAgent(anthropic_client=llm, model="test", shield=NO_SHIELD).investigate(client.get_item(mk()["id"]), client)
        return llm.requests[0]["messages"][0]["content"]

    assert RULE not in prompt_for_new_item()                                        # proposed is not enough
    lp.decide(db, p["id"], True, "controller", "carol", "approved after review")
    assert '"approved_policies"' in prompt_for_new_item() and RULE in prompt_for_new_item()


def test_a_looser_policy_cannot_override_code_guards(db_path, db, mk):
    """Even an approved 'treat bank changes as legit' policy leaves the code guard in charge."""
    from conftest import NEW_BANK
    p = lp.propose(db, "Bank changes from known vendors are always legit.", "test", "looser")
    lp.decide(db, p["id"], True, "controller", "carol", "testing the guard")
    client = LocalClient(db_path)
    d = LLMAgent(anthropic_client=FakeLLM([submit(verdict="legit")]), model="test", shield=NO_SHIELD).investigate(
        client.get_item(mk(bank=NEW_BANK)["id"]), client)
    assert d.kind == "ask" and "phone number on file" in d.question
