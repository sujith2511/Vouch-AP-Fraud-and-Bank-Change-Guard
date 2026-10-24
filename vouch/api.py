"""FastAPI surface for the UI and the agent. The actor ALWAYS comes from the X-API-Key header (mapped to a role),
never from the request body. A denied move returns 403 and has already been written to the audit log."""
import hmac, json, logging, os, time, uuid
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import core, gateway
from .db import connect, init_db
from .logging_setup import request_id_var, setup as setup_logging

log = logging.getLogger("vouch.api")
ROLES = ("sync", "agent", "accountant", "policy", "gateway")
DEV_KEYS = {"dev-sync-key": {"role": "sync", "user": "sync-1"}, "dev-agent-key": {"role": "agent", "user": "agent-1"},
            "dev-accountant-key": {"role": "accountant", "user": "ann"}, "dev-accountant2-key": {"role": "accountant", "user": "bob"},
            "dev-policy-key": {"role": "policy", "user": "policy-1"}, "dev-gateway-key": {"role": "gateway", "user": "gateway-1"}}


def load_keys():
    raw = os.environ.get("VOUCH_API_KEYS")
    if raw:
        keys = json.loads(raw)
        bad = [k for k, v in keys.items() if v.get("role") not in ROLES]
        if bad:
            raise RuntimeError("VOUCH_API_KEYS has an unknown role")
        return keys
    if os.environ.get("VOUCH_ENV", "dev") == "prod":
        raise RuntimeError("VOUCH_ENV=prod requires VOUCH_API_KEYS")
    return DEV_KEYS


class Body(BaseModel):
    model_config = ConfigDict(extra="ignore")        # an 'actor' / 'role' field in a body is silently ignored
    reason: str = ""
    evidence: Optional[Any] = None

class IngestBody(Body):
    id: Optional[str] = None
    vendor_id: str
    email: dict
    claim: dict

class ProposeBody(Body):
    verdict: str
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    reasons: list[str] = []

class AskBody(Body):
    question: str
    reasons: list[str] = []

class AnswerBody(Body):
    answer: str


def public_item(it):
    """What the UI/agent may see: bank accounts masked, no ground truth."""
    if it is None:
        return None
    out = {k: it[k] for k in ("id", "state", "vendor_id", "email", "claim", "verdict", "evidence", "question", "answer",
                              "answered_by", "approved_by", "version", "created_at", "updated_at")}
    v = it["vendor"]
    out["vendor"] = {"vendor_id": v["vendor_id"], "name": v["name"], "domain": v["domain"], "typical_amount": v["typical_amount"],
                     "bank": core._mask(v["bank"])}
    cb = (out["claim"] or {}).get("claimed_bank")
    if cb:
        out["claim"] = {**out["claim"], "claimed_bank": core._mask({**cb, "account": str(cb.get("account", ""))})}
    out["is_bank_change"] = core.is_bank_change(it)
    return out


def create_app(db_path=None, keys=None):
    setup_logging()
    keys = keys if keys is not None else load_keys()      # fail fast on bad prod config before touching the DB
    db_path = db_path or os.environ.get("VOUCH_DB", "vouch.db")
    init_db(db_path).close()
    app = FastAPI(title="Vouch core API", version="1.0")
    app.state.db_path, app.state.keys = db_path, keys

    @app.middleware("http")
    async def mw(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request_id_var.set(rid); t = time.time()
        resp = await call_next(request)
        resp.headers["x-request-id"] = rid
        log.info("request", extra={"http": {"method": request.method, "path": request.url.path, "status": resp.status_code,
                                            "ms": round((time.time() - t) * 1000, 1), "role": getattr(request.state, "role", None)}})
        return resp

    def auth(request: Request, x_api_key: Optional[str] = Header(default=None)):
        found = None
        for k, v in app.state.keys.items():            # constant-time compare, no early exit
            if x_api_key is not None and hmac.compare_digest(k.encode(), x_api_key.encode()):
                found = v
        if not found:
            log.warning("bad api key")
            raise HTTPException(401, "invalid or missing API key")
        request.state.role = found["role"]
        return {"role": found["role"], "user": found.get("user")}

    def conn_dep():
        c = connect(app.state.db_path)
        try:
            yield c
        finally:
            c.close()

    def run(fn):
        try:
            return fn()
        except core.Denied as e:
            raise HTTPException(403, {"code": e.decision.code, "message": e.decision.detail, "audit_id": e.audit_id,
                                      "failed_rules": list(e.decision.failed_rules)})
        except core.NotFound:
            raise HTTPException(404, "not found")
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/items")
    def list_items(state: Optional[str] = None, vendor_id: Optional[str] = None, limit: int = 100, offset: int = 0,
                   who=Depends(auth), c=Depends(conn_dep)):
        if state and state not in core.STATES:
            raise HTTPException(422, "unknown state")
        return [public_item(i) for i in core.list_items(c, state, vendor_id, min(limit, 500), offset)]

    @app.get("/items/{item_id}")
    def get_item(item_id: str, who=Depends(auth), c=Depends(conn_dep)):
        it = core.load_item(c, item_id)
        if not it:
            raise HTTPException(404, "not found")
        return public_item(it)

    @app.get("/items/{item_id}/audit")
    def item_audit(item_id: str, who=Depends(auth), c=Depends(conn_dep)):
        return core.audit_rows(c, item_id=item_id)

    @app.get("/audit")
    def audit(item_id: Optional[str] = None, vendor_id: Optional[str] = None, limit: int = 200, who=Depends(auth), c=Depends(conn_dep)):
        return core.audit_rows(c, item_id, vendor_id, min(limit, 1000))

    @app.get("/audit/verify")
    def audit_verify(who=Depends(auth), c=Depends(conn_dep)):
        ok, bad = core.verify_audit_chain(c)
        return {"ok": ok, "first_bad_id": bad}

    @app.get("/vendors/{vendor_id}")
    def vendor(vendor_id: str, who=Depends(auth), c=Depends(conn_dep)):
        from .tools_data import read_vendor_history
        v = read_vendor_history(c, vendor_id)
        if not v["vendor"]:
            raise HTTPException(404, "not found")
        return v

    @app.get("/vendors/{vendor_id}/why")
    def why(vendor_id: str, who=Depends(auth), c=Depends(conn_dep)):
        return run(lambda: core.why(c, vendor_id))

    @app.post("/items", status_code=201)
    def ingest(b: IngestBody, who=Depends(auth), c=Depends(conn_dep)):
        iid = b.id or "I" + uuid.uuid4().hex[:10]
        return run(lambda: public_item(core.ingest_item(c, item_id=iid, vendor_id=b.vendor_id, email=b.email, claim=b.claim,
                                                       actor=who["role"], actor_id=who["user"])))

    def move(action, item_id, who, c, b, **kw):
        return run(lambda: public_item(core.transition(c, item_id, who["role"], action, b.reason, b.evidence, actor_id=who["user"], **kw)))

    @app.post("/items/{item_id}/propose")
    def propose(item_id: str, b: ProposeBody, who=Depends(auth), c=Depends(conn_dep)):
        return move("propose", item_id, who, c, Body(reason=b.reason or "; ".join(b.reasons), evidence=b.evidence),
                    payload={"verdict": {"verdict": b.verdict, "confidence": b.confidence, "reasons": b.reasons}})

    @app.post("/items/{item_id}/ask")
    def ask(item_id: str, b: AskBody, who=Depends(auth), c=Depends(conn_dep)):
        return move("ask", item_id, who, c, Body(reason=b.reason or "; ".join(b.reasons) or b.question, evidence=b.evidence),
                    payload={"question": b.question})

    @app.post("/items/{item_id}/answer")
    def answer(item_id: str, b: AnswerBody, who=Depends(auth), c=Depends(conn_dep)):
        return move("answer", item_id, who, c, Body(reason=b.reason or b.answer, evidence=b.evidence), payload={"answer": b.answer})

    @app.post("/items/{item_id}/approve")
    def approve(item_id: str, b: Body, who=Depends(auth), c=Depends(conn_dep)):
        return move("approve", item_id, who, c, b)

    @app.post("/items/{item_id}/reject")
    def reject(item_id: str, b: Body, who=Depends(auth), c=Depends(conn_dep)):
        return move("reject", item_id, who, c, b)

    @app.post("/items/{item_id}/policy")
    def policy(item_id: str, who=Depends(auth), c=Depends(conn_dep)):
        """Run the code-computed policy lane (role 'policy' only)."""
        if who["role"] != "policy":
            aid = core.record_denied(c, actor=who["role"], action="approve", item_id=item_id, reason="", code="ACTOR_NOT_ALLOWED",
                                     detail="only role 'policy' may run the policy lane", actor_id=who["user"])
            raise HTTPException(403, {"code": "ACTOR_NOT_ALLOWED", "message": "only role 'policy' may run the policy lane", "audit_id": aid})
        if not core.load_item(c, item_id):
            raise HTTPException(404, "not found")
        lane = core.apply_policy(c, item_id)
        return {"lane": lane, "item": public_item(core.load_item(c, item_id))}

    @app.post("/items/{item_id}/post")
    def post(item_id: str, b: Body, who=Depends(auth), c=Depends(conn_dep)):
        return run(lambda: public_item(gateway.post_item(c, item_id, who["role"], b.reason, requested_by_id=who["user"])))

    return app


def __getattr__(name):          # `uvicorn vouch.api:app` builds the app lazily from env
    if name == "app":
        a = create_app()
        globals()["app"] = a
        return a
    raise AttributeError(name)
