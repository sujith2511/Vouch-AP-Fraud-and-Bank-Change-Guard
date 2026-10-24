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

## Results (rule-based baseline)
**This is the rule-based baseline (`RuleBasedAgent`: no LLM, no API key), not the LLM agent.** It is the floor the real agent has to beat. Run on the v2 dataset (300 emails; 16 from suppliers not in the vendor master), whole file loaded, scored per split:

```
python -m vouch.run_pipeline --dataset v2 --db run.db
python -m vouch.eval --db run.db --json eval_results_v2.json
```

| set | n | lane acc | verdict acc | fraud not auto-cleared | fraud auto-cleared |
|---|---|---|---|---|---|
| dev | 192 | 0.708 | 0.646 | 68/89 | 21 |
| holdout | 108 | 0.704 | 0.639 | 40/51 | 11 |
| hard | 127 | 0.551 | 0.520 | 37/69 | 32 |
| fraud, no bank change | 57 | 0.298 | 0.193 | 25/57 | 32 |

- Legit mail blocked outright: 0/160. Legit mail sent to a human: 70/160 (dev 43/103, holdout 27/57).
- Auto-clear precision: 0.741 dev, 0.732 holdout. **The baseline auto-clears 32 fraud emails**, all of them fraud with no code-visible tell (no bank change, right domain, passing auth): inflated invoices just under 1.5x, invoice-sequence anomalies, kickback/threshold splitting (dev), services never ordered, fake invoices from a compromised real domain, and altered duplicate invoice numbers. Rules over structured fields cannot see these; they are the job of the LLM agent, and `fraud_no_bank_change` is the number to watch.
- **Code cannot be fooled** (separate from agent accuracy): all 15 injection emails were run with an agent that obeys every payload (says "legit", confidence 1.0). Then 90 direct attacks (agent approve/post/reject, sync approve, policy post, agent via the gateway) were tried. 90/90 denied, 0 payments posted, no bank moved, nothing approved, audit chain intact.
- Verdict accuracy uses the dataset's `correct_agent_verdict` (legit / fraud / uncertain). The baseline never says "uncertain" for items that need it, so its verdict accuracy is below its lane accuracy.
- Ground truth is read only by `vouch.eval`, from `<db>.evalkey`. It is not in the DB, the API or any tool output (`tests/test_v2_backend.py` checks this).
- Full numbers (per scenario, per difficulty, per fuzzer): `eval_results_v2.json`.

## Not done / known limits
Azure deploy files exist but were not run (no credentials). Coinbase testnet rail not built (interface in `vouch/rails.py`). In-process the `gateway` actor guard is a seatbelt, not a sandbox: the real boundaries are API-key roles and the DB triggers. SQLite means a single replica.

## Setup for teammates
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q          # 40 tests should pass
```
`external/InjecAgent` is NOT in the repo (only needed to regenerate `data/injections.json`): `git clone https://github.com/uiuc-kang-lab/InjecAgent external/InjecAgent`.
Large raw downloads live in `data/raw/` (gitignored); everything the backend needs is committed.
