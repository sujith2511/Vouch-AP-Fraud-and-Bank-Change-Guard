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

## Web verification (Bright Data): what is simulated, live, recorded
`vouch/web_verify.py` (Sujith) looks a vendor up on the public web and compares the official phone with numbers in the email. It skips fictional vendors, so on the eval set it never ran. Three layers now exist, and every result says which one it is:

| layer | where | label | when |
|---|---|---|---|
| **live** | `web_verify.verify_vendor_web` -> Bright Data SERP | `"source": "live"` | real demo companies, when `BRIGHT_DATA_API_KEY` and `BRIGHT_DATA_SERP_ZONE` are set and the call succeeds |
| **recorded** | `data/v2/web_verify_fixtures/<id>.json`, replayed through the same function | `"source": "recorded"`, plus `"placeholder": true` until real data is recorded | real demo companies, key missing or call blocked/failed (`live_attempt` says why) |
| **simulated** | `vouch/web_sim.py`: directory built from `data/v2/vendors.v2.json`, replayed through the same function | `"simulated": true` on every result and in the results file | fictional v2 vendors, only with `--web sim` |

The simulated official phone is the vendor's phone on file, so it shows the plumbing and the guard working; it says nothing about how the live web behaves. A blocked, empty, error or not_configured result is never reassurance (`LLMAgent._guard` escalates it).

**Eval with the simulated web** (default is off, so existing results do not change):
```
python -m vouch.run_pipeline --dataset v2 --agent vouch.llm_agent:LLMAgent --web sim --db run_websim.db
python -m vouch.eval --db run_websim.db --web sim        # writes eval_results_v2_llm_websim.json (simulated_web: true) and compares with eval_results_v2_llm.json
```
**That real-agent run has not been done yet** (no API key where this was built); it has to be run by whoever has `ANTHROPIC_API_KEY`. The code path was verified with a stub in place of the model (`--agent vouch.web_sim:StubLLMAgent`): the real `LLMAgent` guard and web check run, the model always says "legit", so every stricter outcome comes from the code. Stub numbers (not committed, not the LLM): the web check escalated 232 of 284 items for an "unlisted phone number", but 209 of those flagged only long digit runs. `web_verify.PHONE_RE` has no digit boundaries, so PO and invoice numbers such as `000053180001` read as phone numbers. Counting only real phone numbers (bounded pattern, scratch run, `web_verify.py` unchanged) 75 of 300 emails contain one, and only 3 get flagged, all fraud, none legit. Suggested one-line fix for Sujith: wrap the pattern in `(?<!\d)...(?!\d)`.

**Demo endpoints** (same rule as `/demo/inject`: on unless `VOUCH_ENV=prod`, or `DEMO_ENDPOINTS=1`; any valid key may GET, only sync/accountant keys may POST):
- `GET /demo/verify/{DEMO-R1..R4}`: official phones, official site, phone-on-file match and status for the real demo companies (domain = host of the file's `website.final_url`).
- `POST /demo/real-claim {"demo_vendor_id": "DEMO-R1"}`: an outsider emails that Motorola Solutions moved its bank and asks the AP team to call a number that is not on the company's web listings. One work item runs through the normal pipeline (state machine, `can()`, audit log, agent and guards). The vendor of record is inserted into the live DB only, flagged `demo`; the seed loader still refuses the demo file and eval ignores demo items. The response includes `web_verification` and a `phone_check` block (number in the email vs official numbers on the web). The scene's text lives in `vouch/demo.py`, nowhere under `data/`. Without `ANTHROPIC_API_KEY` the rule-based agent is used and the web result is recorded as evidence.

**Recording real fixtures** (one paid search per company, overwrites the placeholders, writes a timestamp):
```
BRIGHT_DATA_API_KEY=... BRIGHT_DATA_SERP_ZONE=... python scripts/record_web_verify.py
python scripts/record_web_verify.py --placeholders       # offline: rewrite the placeholders
```
Env vars: `BRIGHT_DATA_API_KEY`, `BRIGHT_DATA_SERP_ZONE` (SERP API zone, full JSON), `ANTHROPIC_API_KEY` (LLM agent), `DEMO_ENDPOINTS`, `VOUCH_ENV`.

## Not done / known limits
Azure deploy files exist but were not run (no credentials). Coinbase testnet rail not built (interface in `vouch/rails.py`). In-process the `gateway` actor guard is a seatbelt, not a sandbox: the real boundaries are API-key roles and the DB triggers. SQLite means a single replica.

## Setup for teammates
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q          # 40 tests should pass
```
`external/InjecAgent` is NOT in the repo (only needed to regenerate `data/injections.json`): `git clone https://github.com/uiuc-kang-lab/InjecAgent external/InjecAgent`.
Large raw downloads live in `data/raw/` (gitignored); everything the backend needs is committed.
