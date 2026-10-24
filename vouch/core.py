"""The rulebook and the record.

The agent only PROPOSES. Everything that changes state passes through transition(), which calls can() and writes the
audit row in the same transaction. Free text (agent reasons, email bodies) is stored and logged but never read by any rule.
"""
import hashlib, json, logging, sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parseaddr

log = logging.getLogger("vouch.audit")

STATES = ("NEW", "PROPOSED", "NEEDS_INFO", "APPROVED", "REJECTED", "POSTED")
ACTORS = ("sync", "agent", "accountant", "policy", "gateway")
VERDICTS = ("legit", "fraud", "uncertain")
AMOUNT_FACTOR = 1.5

# action -> (actors allowed, required from-state, resulting state)
MOVES = {
    "ingest":  ({"sync"},                   None,         "NEW"),
    "propose": ({"agent"},                  "NEW",        "PROPOSED"),
    "ask":     ({"agent"},                  "PROPOSED",   "NEEDS_INFO"),
    "answer":  ({"accountant"},             "NEEDS_INFO", "PROPOSED"),
    "approve": ({"accountant", "policy"},   "PROPOSED",   "APPROVED"),
    "reject":  ({"accountant", "policy"},   "PROPOSED",   "REJECTED"),
    "post":    ({"gateway"},                "APPROVED",   "POSTED"),
}
_GATEWAY_KEY = object()   # handed only to gateway.py; guards against accidental/injected use of actor="gateway"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def jdump(o):
    return json.dumps(o, sort_keys=True, default=str)


class NotFound(Exception):
    pass


@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str = "OK"
    detail: str = ""
    failed_rules: tuple = field(default_factory=tuple)


class Denied(Exception):
    def __init__(self, decision, audit_id):
        super().__init__(f"{decision.code}: {decision.detail}")
        self.decision, self.audit_id = decision, audit_id


# ---------------------------------------------------------------- loading
def _vendor(conn, vendor_id):
    r = conn.execute("SELECT * FROM vendors WHERE vendor_id=?", (vendor_id,)).fetchone()
    if not r:
        return None
    return {"vendor_id": r["vendor_id"], "name": r["name"], "domain": r["domain"], "typical_amount": r["typical_amount"],
            "bank": {"bank_name": r["bank_name"], "routing": r["bank_routing"], "account": r["bank_account"]},
            "phone": r["phone"], "split": r["split"]}


def load_item(conn, item_id):
    r = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not r:
        return None
    j = lambda s: json.loads(s) if s else None
    return {"id": r["id"], "state": r["state"], "vendor_id": r["vendor_id"], "vendor": _vendor(conn, r["vendor_id"]),
            "email": j(r["email"]), "claim": j(r["claim"]), "verdict": j(r["verdict"]), "evidence": j(r["evidence"]) or [],
            "question": r["question"], "answer": r["answer"], "answered_by": r["answered_by"], "approved_by": r["approved_by"],
            "version": r["version"], "created_at": r["created_at"], "updated_at": r["updated_at"]}


# ---------------------------------------------------------------- code-computed risk facts (agent text never read)
def _domain(addr):
    a = parseaddr(addr or "")[1].lower()
    return a.rsplit("@", 1)[1] if "@" in a else ""


def is_bank_change(item):
    cb = (item.get("claim") or {}).get("claimed_bank")
    if not cb:
        return False
    cur = item["vendor"]["bank"]
    return (str(cb.get("routing")), str(cb.get("account"))) != (str(cur["routing"]), str(cur["account"]))


def policy_check(conn, item):
    """Low-risk check, computed from structured fields only. Returns {rule: bool}. The agent contributes exactly one
    enum value (verdict.verdict == 'legit'); its reasons / confidence / evidence text are never inspected."""
    email, claim, vendor, verdict = item["email"] or {}, item["claim"] or {}, item["vendor"], item["verdict"] or {}
    auth = email.get("auth") or {}
    amount = claim.get("amount")
    dup = False
    if claim.get("invoice_number") and conn is not None:
        inv = claim["invoice_number"]
        # same vendor + invoice number as an EARLIER non-rejected item, or as a voucher already in payment history
        dup = conn.execute("""SELECT 1 FROM items WHERE vendor_id=? AND id!=? AND state!='REJECTED'
                              AND json_extract(claim,'$.invoice_number')=? AND (created_at, id) < (?, ?)""",
                           (item["vendor_id"], item["id"], inv, item["created_at"], item["id"])).fetchone() is not None
        dup = dup or conn.execute("SELECT 1 FROM payment_history WHERE vendor_id=? AND voucher=?", (item["vendor_id"], inv)).fetchone() is not None
    return {
        "valid_claim": isinstance(amount, (int, float)) and amount > 0 and bool(claim.get("invoice_number")),
        "no_bank_change": not is_bank_change(item),
        "auth_all_pass": all(auth.get(k) == "pass" for k in ("spf", "dkim", "dmarc")),
        "sender_domain_is_vendor": _domain(email.get("from")) == vendor["domain"].lower(),
        "reply_to_domain_is_vendor": _domain(email.get("reply_to") or email.get("from")) == vendor["domain"].lower(),
        "amount_within_1_5x_typical": isinstance(amount, (int, float)) and amount <= AMOUNT_FACTOR * vendor["typical_amount"],
        "not_duplicate_invoice": not dup,
        "agent_verdict_legit": verdict.get("verdict") == "legit",
    }


def policy_low_risk(conn, item):
    rules = policy_check(conn, item)
    return all(rules.values()), tuple(k for k, v in rules.items() if not v)


def hard_reject_signals(item):
    """Clear spoof: sender domain is not the vendor's AND the mail fails authentication, or the agent says fraud
    and the sender domain is wrong. Can only make handling stricter; never loosens anything."""
    email, vendor, verdict = item["email"] or {}, item["vendor"], item["verdict"] or {}
    auth = email.get("auth") or {}
    off_domain = _domain(email.get("from")) != vendor["domain"].lower()
    auth_bad = any(auth.get(k) != "pass" for k in ("spf", "dkim", "dmarc"))
    return off_domain and (auth_bad or verdict.get("verdict") == "fraud")


def compute_lane(conn, item):
    ok, _ = policy_low_risk(conn, item)
    if ok:
        return "auto_clear"
    return "reject" if hard_reject_signals(item) else "human_review"


# ---------------------------------------------------------------- the one rule function
def can(actor, action, item, conn=None, actor_id=None, reason=""):
    """Every move passes through here. `item` is a load_item() dict (None only for 'ingest')."""
    if action not in MOVES:
        return Decision(False, "UNKNOWN_ACTION", f"unknown action {action!r}")
    allowed_actors, from_state, _ = MOVES[action]
    if actor not in ACTORS:
        return Decision(False, "UNKNOWN_ACTOR", f"unknown actor {actor!r}")
    if actor not in allowed_actors:
        return Decision(False, "ACTOR_NOT_ALLOWED", f"{actor} may not {action}")
    if action == "ingest":
        return Decision(True)
    if item is None:
        return Decision(False, "ITEM_NOT_FOUND", "no such item")
    if item["state"] != from_state:
        return Decision(False, "BAD_STATE", f"{action} requires {from_state}, item is {item['state']}")
    if actor == "accountant" and action in ("approve", "reject") and len((reason or "").strip()) < 5:
        return Decision(False, "REASON_REQUIRED", "accountant decisions need a written reason")
    if action == "approve" and is_bank_change(item):
        if actor == "policy":
            return Decision(False, "POLICY_CANNOT_APPROVE_BANK_CHANGE", "bank changes need a human")
        if actor_id and item.get("answered_by") and actor_id == item["answered_by"]:
            return Decision(False, "SEPARATION_OF_DUTIES", "approver must differ from the accountant who answered the question")
    if actor == "policy" and action == "approve":
        ok, failed = policy_low_risk(conn, item)
        if not ok:
            return Decision(False, "POLICY_RULES_FAILED", "low-risk check failed: " + ",".join(failed), failed)
    if actor == "policy" and action == "reject" and not hard_reject_signals(item):
        return Decision(False, "POLICY_NO_REJECT_SIGNAL", "no code-computed reject signal")
    return Decision(True)


# ---------------------------------------------------------------- audit
def append_audit(conn, *, actor, action, outcome, item_id=None, vendor_id=None, actor_id=None, deny_code=None,
                 from_state=None, to_state=None, reason=None, evidence=None, before=None, after=None):
    """Append one hash-chained row. Must run inside the caller's transaction (BEGIN IMMEDIATE serialises writers)."""
    prev = conn.execute("SELECT row_hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = prev["row_hash"] if prev else "0" * 64
    row = {"ts": now(), "item_id": item_id, "vendor_id": vendor_id, "actor": actor, "actor_id": actor_id, "action": action,
           "outcome": outcome, "deny_code": deny_code, "from_state": from_state, "to_state": to_state, "reason": reason,
           "evidence": jdump(evidence) if evidence is not None else None,
           "before": jdump(before) if before is not None else None, "after": jdump(after) if after is not None else None}
    row_hash = hashlib.sha256((prev_hash + jdump(row)).encode()).hexdigest()
    cur = conn.execute(
        "INSERT INTO audit(ts,item_id,vendor_id,actor,actor_id,action,outcome,deny_code,from_state,to_state,reason,evidence,before,after,prev_hash,row_hash)"
        " VALUES(:ts,:item_id,:vendor_id,:actor,:actor_id,:action,:outcome,:deny_code,:from_state,:to_state,:reason,:evidence,:before,:after,:p,:h)",
        {**row, "p": prev_hash, "h": row_hash})
    log.info("audit", extra={"audit": {**row, "id": cur.lastrowid, "evidence": None}})
    return cur.lastrowid


def verify_audit_chain(conn):
    """Recompute the hash chain. Returns (ok, first_bad_id). Detects edits made by bypassing the triggers (e.g. file tampering)."""
    prev = "0" * 64
    for r in conn.execute("SELECT * FROM audit ORDER BY id"):
        row = {k: r[k] for k in ("ts", "item_id", "vendor_id", "actor", "actor_id", "action", "outcome", "deny_code",
                                 "from_state", "to_state", "reason", "evidence", "before", "after")}
        if r["prev_hash"] != prev or hashlib.sha256((prev + jdump(row)).encode()).hexdigest() != r["row_hash"]:
            return False, r["id"]
        prev = r["row_hash"]
    return True, None


def record_denied(conn, *, actor, action, item_id, reason, code, detail="", actor_id=None, evidence=None, state=None, vendor_id=None):
    """Write a standalone 'denied' row (own transaction). Used by transition() and by gateway for refused requesters."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        aid = append_audit(conn, actor=actor, action=action, outcome="denied", item_id=item_id, vendor_id=vendor_id,
                           actor_id=actor_id, deny_code=code, from_state=state, reason=reason,
                           evidence={"detail": detail, "evidence": evidence})
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK"); raise
    return aid


# ---------------------------------------------------------------- transitions
def _validate_verdict(v):
    if not isinstance(v, dict) or v.get("verdict") not in VERDICTS:
        raise ValueError(f"verdict.verdict must be one of {VERDICTS}")
    c = v.get("confidence")
    if c is not None and not (isinstance(c, (int, float)) and 0 <= c <= 1):
        raise ValueError("confidence must be in [0,1]")
    return {"verdict": v["verdict"], "confidence": c, "reasons": [str(x) for x in (v.get("reasons") or [])][:20]}


def ingest_item(conn, *, item_id, vendor_id, email, claim, truth=None, split=None, actor="sync", actor_id=None):
    """(new) -> NEW, actor sync. Item row + audit row in one transaction."""
    dec = can(actor, "ingest", None)
    if not dec.allowed:
        aid = record_denied(conn, actor=actor, action="ingest", item_id=item_id, reason="", code=dec.code, detail=dec.detail, actor_id=actor_id)
        raise Denied(dec, aid)
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone():
            conn.execute("ROLLBACK")
            d = Decision(False, "DUPLICATE_ITEM", f"{item_id} exists")
            raise Denied(d, record_denied(conn, actor=actor, action="ingest", item_id=item_id, reason="", code=d.code, actor_id=actor_id))
        if not _vendor(conn, vendor_id):
            conn.execute("ROLLBACK")
            d = Decision(False, "VENDOR_UNKNOWN", vendor_id)
            raise Denied(d, record_denied(conn, actor=actor, action="ingest", item_id=item_id, reason="", code=d.code, actor_id=actor_id))
        t = now()
        append_audit(conn, actor=actor, actor_id=actor_id, action="ingest", outcome="applied", item_id=item_id, vendor_id=vendor_id,
                     to_state="NEW", reason="ingested", after={"vendor_id": vendor_id, "claim": claim})
        conn.execute("INSERT INTO items(id,state,vendor_id,email,claim,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                     (item_id, "NEW", vendor_id, jdump(email), jdump(claim), t, t))
        if truth is not None:
            conn.execute("INSERT INTO truth(item_id,split,truth) VALUES(?,?,?)", (item_id, split, jdump(truth)))
        conn.execute("COMMIT")
    except Denied:
        raise
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return load_item(conn, item_id)


def transition(conn, item_id, actor, action, reason="", evidence=None, *, actor_id=None, payload=None, effects=None, _gateway_key=None):
    """Check can(), apply the change and write the audit row in ONE transaction. A denial writes a 'denied' row (with the
    actor's stated reason) and raises Denied. `effects(conn, item)` runs inside the same transaction (used by gateway.post);
    if it raises, the state change and audit row roll back together."""
    payload = payload or {}
    conn.execute("BEGIN IMMEDIATE")
    denied = None
    try:
        item = load_item(conn, item_id)
        dec = can(actor, action, item, conn, actor_id, reason)
        if dec.allowed and actor == "gateway" and _gateway_key is not _GATEWAY_KEY:
            dec = Decision(False, "GATEWAY_ONLY", "actor 'gateway' may only be used by the gateway module")
        if dec.allowed:
            from_state, to_state = item["state"], MOVES[action][2]
            sets, args = {"state": to_state, "updated_at": now(), "version": item["version"] + 1}, {}
            if action == "propose":
                sets["verdict"] = jdump(_validate_verdict(payload.get("verdict")))
            if action == "ask":
                sets["question"] = str(payload.get("question", ""))[:2000]
            if action == "answer":
                sets["answer"] = str(payload.get("answer", ""))[:4000]; sets["answered_by"] = actor_id or actor
            if action == "approve":
                sets["approved_by"] = actor_id or actor
            if evidence:
                sets["evidence"] = jdump(item["evidence"] + [{"by": actor, "action": action, "data": evidence}])
            audit_id = append_audit(conn, actor=actor, actor_id=actor_id, action=action, outcome="applied", item_id=item_id,
                                    vendor_id=item["vendor_id"], from_state=from_state, to_state=to_state, reason=reason,
                                    evidence=evidence, before={"state": from_state},
                                    after={"state": to_state, **({"verdict": json.loads(sets["verdict"])} if "verdict" in sets else {})})
            conn.execute(f"UPDATE items SET {', '.join(k + '=:' + k for k in sets)} WHERE id=:_id", {**sets, "_id": item_id})
            if effects:
                effects(conn, item)
            conn.execute("COMMIT")
            return load_item(conn, item_id)
        denied = dec
        append_audit(conn, actor=actor, actor_id=actor_id, action=action, outcome="denied", item_id=item_id,
                     vendor_id=item["vendor_id"] if item else None, deny_code=dec.code,
                     from_state=item["state"] if item else None, reason=reason,
                     evidence={"detail": dec.detail, "failed_rules": list(dec.failed_rules), "evidence": evidence})
        audit_id = conn.execute("SELECT MAX(id) m FROM audit").fetchone()["m"]
        conn.execute("COMMIT")
    except Exception as e:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        try:   # state change + audit row rolled back together; leave a separate 'error' row so the failure is visible
            conn.execute("BEGIN IMMEDIATE")
            append_audit(conn, actor=actor, actor_id=actor_id, action=action, outcome="error", item_id=item_id,
                         reason=reason, evidence={"error": repr(e)})
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
        raise
    if item is None:
        raise NotFound(item_id)
    raise Denied(denied, audit_id)


def propose(conn, item_id, verdict, confidence=None, reasons=(), evidence=None, actor_id=None):
    return transition(conn, item_id, "agent", "propose", "; ".join(map(str, reasons))[:2000], evidence, actor_id=actor_id,
                      payload={"verdict": {"verdict": verdict, "confidence": confidence, "reasons": list(reasons)}})


def ask(conn, item_id, question, reasons=(), evidence=None, actor_id=None):
    return transition(conn, item_id, "agent", "ask", "; ".join(map(str, reasons))[:2000] or question, evidence, actor_id=actor_id,
                      payload={"question": question})


def apply_policy(conn, item_id):
    """Run the policy lane: approve iff low-risk, reject iff clear spoof, else leave for a human. Returns the lane."""
    item = load_item(conn, item_id)
    if item is None or item["state"] != "PROPOSED":
        return "human_review" if item and item["state"] == "NEEDS_INFO" else "none"
    lane = compute_lane(conn, item)
    rules = policy_check(conn, item)
    if lane == "auto_clear":
        transition(conn, item_id, "policy", "approve", "policy: all low-risk rules passed", {"rules": rules})
    elif lane == "reject":
        transition(conn, item_id, "policy", "reject", "policy: off-domain sender with failed auth / fraud verdict", {"rules": rules})
    return lane


# ---------------------------------------------------------------- reads
def list_items(conn, state=None, vendor_id=None, limit=100, offset=0):
    q, a = "SELECT id FROM items WHERE 1=1", []
    if state:
        q += " AND state=?"; a.append(state)
    if vendor_id:
        q += " AND vendor_id=?"; a.append(vendor_id)
    q += " ORDER BY created_at, id LIMIT ? OFFSET ?"
    return [load_item(conn, r["id"]) for r in conn.execute(q, a + [limit, offset])]


def audit_rows(conn, item_id=None, vendor_id=None, limit=500):
    q, a = "SELECT * FROM audit WHERE 1=1", []
    if item_id:
        q += " AND item_id=?"; a.append(item_id)
    if vendor_id:
        q += " AND vendor_id=?"; a.append(vendor_id)
    rows = conn.execute(q + " ORDER BY id LIMIT ?", a + [limit]).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("evidence", "before", "after"):
            d[k] = json.loads(d[k]) if d[k] else None
        out.append(d)
    return out


def _mask(b):
    if not b:
        return b
    acct = str(b.get("account") or "")
    return {**b, "account": "*" * max(0, len(acct) - 4) + acct[-4:]}


def why(conn, vendor_id):
    """Answer 'why was this vendor's bank changed?' from the audit log alone."""
    if not _vendor(conn, vendor_id):
        raise NotFound(vendor_id)
    changes = []
    for r in audit_rows(conn, vendor_id=vendor_id):
        if r["action"] != "bank_change" or r["outcome"] != "applied":
            continue
        trail = audit_rows(conn, item_id=r["item_id"])
        applied = [t for t in trail if t["outcome"] == "applied"]
        find = lambda act: next((t for t in reversed(applied) if t["action"] == act), None)
        prop, appr, post = find("propose"), find("approve"), find("post")
        changes.append({
            "changed_at": r["ts"], "item_id": r["item_id"], "before": _mask(r["before"]), "after": _mask(r["after"]),
            "agent_verdict": (prop or {}).get("after", {}).get("verdict") if prop else None,
            "agent_reason": (prop or {}).get("reason"),
            "agent_evidence": (prop or {}).get("evidence"),
            "approved_by": {"actor": appr["actor"], "actor_id": appr["actor_id"], "ts": appr["ts"], "reason": appr["reason"]} if appr else None,
            "posted_at": post["ts"] if post else None,
            "denied_attempts": [{"actor": t["actor"], "action": t["action"], "code": t["deny_code"], "reason": t["reason"]} for t in trail if t["outcome"] == "denied"],
            "audit_trail": [{"id": t["id"], "ts": t["ts"], "actor": t["actor"], "action": t["action"], "outcome": t["outcome"],
                             "from": t["from_state"], "to": t["to_state"]} for t in trail],
        })
    if not changes:
        return {"vendor_id": vendor_id, "changes": [], "summary": "No bank change has been recorded for this vendor."}
    c = changes[-1]
    who = f"{c['approved_by']['actor']}{(' ' + c['approved_by']['actor_id']) if c['approved_by']['actor_id'] else ''}" if c["approved_by"] else "unknown"
    summary = (f"Bank details changed {len(changes)} time(s). Latest: item {c['item_id']} at {c['changed_at']}, approved by {who}"
               f" ({c['approved_by']['reason'] if c['approved_by'] else 'no reason on record'}); agent verdict "
               f"{(c['agent_verdict'] or {}).get('verdict', 'none')}; {len(c['denied_attempts'])} denied attempt(s) on this item.")
    return {"vendor_id": vendor_id, "changes": changes, "summary": summary}
