"""Endpoints the web console uses: /me, /items/{id}/investigate, learned policies, and serving ui/. No network, no tokens."""
from fastapi.testclient import TestClient

from vouch.agent_interface import AgentDecision
from vouch.api import create_app

from test_llm_agent import FakeLLM, tool_use

KEYS = {"k-sync": {"role": "sync", "user": "sync-bot"}, "k-agent": {"role": "agent", "user": "agent-1"},
        "k-ann": {"role": "accountant", "user": "ann"}, "k-carol": {"role": "controller", "user": "carol"}}
H = lambda k: {"X-API-Key": k}


class Says:
    def __init__(self, verdict):
        self.verdict = verdict

    def investigate(self, item, client):
        return AgentDecision("propose", self.verdict, 0.9, [f"scripted {self.verdict}"], [])


def client_for(db_path, agent=None, policy_llm=None):
    app = create_app(db_path, KEYS)
    app.state.agent, app.state.policy_llm = agent, policy_llm
    return TestClient(app)


def test_me_returns_role_from_the_key(db_path):
    c = client_for(db_path)
    assert c.get("/me", headers=H("k-carol")).json() == {"role": "controller", "user": "carol"}
    assert c.get("/me").status_code == 401


def test_investigate_runs_agent_then_policy_lane(db_path, mk):
    it = mk()
    c = client_for(db_path, agent=Says("fraud"))
    r = c.post(f"/items/{it['id']}/investigate", headers=H("k-ann"))
    assert r.status_code == 200 and r.json()["item"]["verdict"]["verdict"] == "fraud" and r.json()["agent"] == "Says"
    assert c.post(f"/items/{it['id']}/investigate", headers=H("k-ann")).status_code == 409      # only NEW items


def test_investigate_is_denied_and_audited_for_the_agent_key(db_path, mk):
    it = mk()
    c = client_for(db_path, agent=Says("legit"))
    r = c.post(f"/items/{it['id']}/investigate", headers=H("k-agent"))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ACTOR_NOT_ALLOWED"
    audit = c.get(f"/items/{it['id']}/audit", headers=H("k-ann")).json()
    assert any(a["outcome"] == "denied" and a["actor"] == "agent" for a in audit)


def test_learned_policy_flow_over_http(db_path, mk):
    it = mk()
    c = client_for(db_path, agent=Says("fraud"), policy_llm=FakeLLM(
        [tool_use("submit_policy", {"rule": "Verify PO-matched invoices from authorized contacts before calling them fraud.",
                                    "rationale": "accountant overruled"})]))
    c.post(f"/items/{it['id']}/investigate", headers=H("k-ann"))
    assert c.post(f"/items/{it['id']}/approve", headers=H("k-ann"), json={"reason": "called vendor on file, genuine"}).status_code == 200
    assert len(c.get("/policies/corrections", headers=H("k-ann")).json()) == 1
    assert c.post("/policies/draft", headers=H("k-agent")).status_code == 403
    drafted = c.post("/policies/draft", headers=H("k-ann")).json()
    assert len(drafted) == 1 and drafted[0]["state"] == "PROPOSED" and drafted[0]["direction"] == "looser"
    pid = drafted[0]["id"]
    r = c.post(f"/policies/{pid}/approve", headers=H("k-ann"), json={"reason": "looks good"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ACTOR_NOT_ALLOWED"
    assert c.post(f"/policies/{pid}/approve", headers=H("k-carol"), json={"reason": "x"}).json()["detail"]["code"] == "REASON_REQUIRED"
    ok = c.post(f"/policies/{pid}/approve", headers=H("k-carol"), json={"reason": "matches our PO-match practice"})
    assert ok.status_code == 200 and ok.json()["state"] == "APPROVED"
    assert [p["state"] for p in c.get("/policies", headers=H("k-ann")).json()] == ["APPROVED"]


def test_draft_without_a_model_key_says_so(db_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client_for(db_path).post("/policies/draft", headers=H("k-ann")).status_code == 503


def test_console_is_served_and_root_redirects(db_path):
    c = client_for(db_path)
    r = c.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/ui/"
    page = c.get("/ui/")
    assert page.status_code == 200 and "Vouch" in page.text
    assert c.get("/ui/app.js").status_code == 200 and c.get("/ui/styles.css").status_code == 200


def test_password_sign_in_returns_the_accountant_key(db_path, monkeypatch):
    c = client_for(db_path)
    assert c.post("/login", json={"username": "calhacks", "password": "pw"}).status_code == 404      # off unless configured
    monkeypatch.setenv("VOUCH_LOGIN_USER", "calhacks"); monkeypatch.setenv("VOUCH_LOGIN_PASSWORD", "s3cret-pass")
    monkeypatch.setenv("VOUCH_LOGIN_AS", "ann")
    r = c.post("/login", json={"username": "CalHacks", "password": "s3cret-pass"})
    assert r.status_code == 200 and r.json() == {"api_key": "k-ann", "role": "accountant", "user": "ann"}
    assert c.get("/me", headers=H(r.json()["api_key"])).json()["role"] == "accountant"
    assert c.post("/login", json={"username": "calhacks", "password": "wrong"}).status_code == 401
    assert c.post("/login", json={"username": "calhacks", "role": "controller", "password": "s3cret-pass"}).json()["role"] == "accountant"


def test_password_sign_in_is_throttled(db_path, monkeypatch):
    monkeypatch.setenv("VOUCH_LOGIN_USER", "calhacks"); monkeypatch.setenv("VOUCH_LOGIN_PASSWORD", "s3cret-pass")
    c = client_for(db_path)
    codes = [c.post("/login", json={"username": "calhacks", "password": f"guess{i}"}).status_code for i in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429
    assert c.post("/login", json={"username": "calhacks", "password": "s3cret-pass"}).status_code == 429
