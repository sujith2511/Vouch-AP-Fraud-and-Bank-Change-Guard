# Vouch core system (Ayushi): rulebook, record, gateway, API

The agent only **proposes**. Code decides what is allowed and logs everything.

```
python -m pytest -q                                   # 40 tests
python -m vouch.run_pipeline --emails data/fixtures/emails_fixture.jsonl --db run.db
python -m vouch.eval --db run.db                      # dev / holdout report (exit 2 if fraud auto-cleared or an injection changed state)
python -m vouch.injection_replay                      # replays all InjecAgent-derived payloads; must report 0 state-changing
VOUCH_DB=vouch.db uvicorn vouch.api:app --port 8000   # dev keys: dev-agent-key, dev-accountant-key, dev-accountant2-key, dev-policy-key, dev-sync-key, dev-gateway-key
```

## State machine (`vouch/core.py`, `MOVES`)
| move | action | who |
|---|---|---|
| (new) -> NEW | ingest | sync |
| NEW -> PROPOSED | propose | agent |
| PROPOSED -> NEEDS_INFO | ask | agent (so an agent that wants to ask must first propose `uncertain`; `run_agent` does it) |
| NEEDS_INFO -> PROPOSED | answer | accountant |
| PROPOSED -> APPROVED | approve | accountant, or policy if the code-computed check passes |
| PROPOSED -> REJECTED | reject | accountant, or policy on a code-computed spoof signal |
| APPROVED -> POSTED | post | gateway only (accountant/gateway may *request* it) |

`REJECTED` is kept in addition to the five states in the team plan (reject needs a terminal state).

## Policy low-risk check (all code-computed from structured fields; agent text is never read)
no bank change vs bank on file; spf/dkim/dmarc all `pass`; sender domain == vendor domain; reply-to domain == vendor domain; amount <= 1.5x vendor typical; claim valid; not a duplicate of an earlier item or a voucher in payment history; and the agent's **verdict enum** is `legit`. The agent can only make handling stricter, never looser.
Lanes: `auto_clear` (policy approves) / `reject` (off-domain sender with failed auth, or fraud verdict + wrong domain) / `human_review` (everything else, including every bank change).

## Integrity (enforced by DB triggers, not just app code)
audit is append-only; an item's state can only change if the audit row just written records that exact move; vendor bank columns only change right after an applied `bank_change` audit row; a payment only exists after an applied `post` row (one per item); audit rows are hash-chained (`GET /audit/verify`). Denied attempts, including the agent's stated reason, are written as `outcome='denied'` rows. Failed effects roll back the state change and its audit row together and leave an `error` row.

## API (header `X-API-Key` -> role; the body can never set the actor; denied = 403 and logged; bad key = 401)
`GET /items?state=&vendor_id=` · `GET /items/{id}` · `GET /items/{id}/audit` · `GET /audit` · `GET /audit/verify` · `GET /vendors/{id}` · `GET /vendors/{id}/why`
`POST /items` (sync) · `/items/{id}/propose` `{verdict: legit|fraud|uncertain, confidence, reasons[], evidence}` (agent) · `/ask` `{question}` (agent) · `/answer` `{answer}` (accountant) · `/approve` `{reason}` · `/reject` `{reason}` · `/policy` (policy role: runs the lane) · `/post` (accountant or gateway key)
Accountant approve/reject need a written reason. Bank-change approval needs a different accountant than the one who answered the question (four-eyes).

## Work-item JSON (the contract): `id, state, vendor_id, vendor{name,domain,typical_amount,bank(masked)}, email{from,reply_to,auth,subject,body}, claim{invoice_number,amount,currency,claimed_bank(masked)}, verdict{verdict,confidence,reasons}, evidence[], question, answer, is_bank_change, version`. Ground truth is never exposed.

## For Sujith
Implement `Agent.investigate(item, client) -> AgentDecision` (`vouch/agent_interface.py`); read tools are `client.read_vendor_history / compare_amounts / check_domain`. Use `LocalClient` in-process or `HttpClient(base_url, agent_key)`. Run with `python -m vouch.run_pipeline --agent pkg.mod:Class`.
## For Xanath
Seed adapters are `_vendor_fields` / `_email_fields` in `vouch/seed.py`; adjust there if your format differs. Items may carry a `truth` object (`label, type, difficulty, expected_lane, ...`) and `split` for `vouch.eval`.

## Not done / known limits
Azure deploy files exist but were not run (no credentials). Coinbase testnet rail not built (interface in `vouch/rails.py`). In-process the `gateway` actor guard is a seatbelt, not a sandbox: the real boundaries are API-key roles and the DB triggers. SQLite means a single replica.

## Setup for teammates
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q          # 40 tests should pass
```
`external/InjecAgent` is NOT in the repo (only needed to regenerate `data/injections.json`): `git clone https://github.com/uiuc-kang-lab/InjecAgent external/InjecAgent`.
Large raw downloads live in `data/raw/` (gitignored); everything the backend needs is committed.
