# Vouch: an AP agent that can't be talked into paying

Built at CalHacks 13 by Ayushi, Sujith and Xanath.

Vouch is an accounts-payable agent that investigates vendor emails, including "we changed our bank account" requests, inflated invoices, fake vendors and hidden prompt injections. It can never move money itself. Only a code-enforced gateway can, and only after a human approves.

**Live:** https://vouch-core.livelygrass-b9211f5e.northcentralus.azurecontainerapps.io. It opens the web console; the API docs are at `/docs`. Judges sign in with the shared demo login (username `calhacks`; ask the team for the password), which acts as an accountant. Other roles, such as the controller, sign in with an API key from the team.

## The problem

In bank-change fraud (business email compromise), an attacker emails a company pretending to be a real vendor and asks that future payments go to a new bank account. A busy AP clerk updates the vendor record, and the next invoice goes to the attacker. Related schemes don't touch the bank at all: an invoice inflated to just under an approval limit, services that were never ordered, or a resent invoice with a new number. All of these are common, costly and hard to catch by eye.

## What Vouch does

1. **Reads** each vendor email, including headers, attachments and quoted history, and extracts the claim: sender, invoice, amount, PO, and any new bank details.
2. **Investigates** with read-only tools:
   - the vendor record and payment history
   - the vendor's past emails
   - the sender domain
   - amount patterns
   - related invoices in the queue

   It also checks the email for hidden instructions with **Azure AI Content Safety Prompt Shields**, and looks up real vendors on the live web with **Bright Data**.
3. **Proposes** a verdict (`legit`, `fraud` or `uncertain`) with reasons and evidence. It asks a human when a check is needed, for example "call the phone number on file, not the one in the email".
4. **Records** every step, including denied attempts, in an append-only, hash-chained audit log, so "why?" is one query.
5. **Learns**: when a human overrules the agent, the agent drafts a general policy, and only a controller can approve it.

## How it works

Every vendor email becomes a work item that moves through fixed states. Code checks each move, not the prompt.

```
NEW -> PROPOSED -> APPROVED -> POSTED
          |  ^  \
          v  |   -> REJECTED
       NEEDS_INFO
```

| State | Who moves it | Meaning |
|---|---|---|
| NEW | Sync job | A vendor email arrived |
| PROPOSED | AI agent | The agent investigated and wrote a verdict with evidence |
| NEEDS_INFO | AI agent | The agent asked a human to verify something. The answer returns the item to PROPOSED |
| APPROVED / REJECTED | Accountant, or the policy lane | A human decided with a written reason. The code-computed policy lane may auto-clear clearly low-risk invoices, or reject clear spoofs. It never approves a bank change |
| POSTED | Gateway only | The only step that changes the vendor record or releases a payment |

### Who may do what

| Actor | Allowed |
|---|---|
| Sync job | Create a work item |
| AI agent | Propose, ask, propose a policy. It has no tool or role that can approve, reject or pay |
| Accountant | Answer, approve or reject items (a written reason is required), request a post |
| Policy lane | Auto-clear or reject from code-computed rules only. Agent text is never read |
| Controller | Approve or reject learned policies |
| Gateway | Post. The only actor that can write to the vendor record |

Separation of duties is enforced in code:
- the agent cannot approve its own proposal
- a bank change needs a different accountant than the one who answered the agent's question
- whoever proposed a policy cannot approve it

Database triggers back this up: an item's state, a vendor's bank details, a payment or a policy cannot change without the matching audit row.

### Audit log

Every move is appended in the same transaction as the change: time, actor, action, outcome, from and to states, reason, evidence, and before and after values. Denied attempts are logged too, and rows are hash-chained (`GET /audit/verify`). Asking "why was this vendor's bank changed?" is one call to `GET /vendors/{id}/why`, or one query:

```sql
SELECT ts, actor, actor_id, action, outcome, from_state, to_state, reason
FROM audit
WHERE item_id = '<work item id>'
ORDER BY id;
```

### Defence in depth against prompt injection

1. **Azure AI Content Safety Prompt Shields** scans the email body and attachments (as documents) before the model reads them.
2. The email is fenced as `<untrusted_email>`, and the agent is told that text addressed to an AI is itself a fraud signal.
3. **Code guards** can only make a verdict stricter. A verdict can never be `legit` when:
   - an injection is detected, by Prompt Shields or by keyword and workflow-command patterns
   - the sender is off-domain
   - the supplier isn't in the vendor master
   - a vendor-detail change is requested
   - the invoice number jumps far past the vendor's last one
   - an invoice is split to stay under the approval limit
   - a callback number isn't one the vendor lists online
4. The **rulebook** ignores agent free text entirely. Even an agent that obeys every injection can't approve or pay. We tested 90 direct attacks, and all 90 were denied.

## Sponsors and where we use them

| Sponsor | Where it is used in Vouch |
|---|---|
| **Hyphenate** | The architecture: work-item state machine, role permissions in code, append-only hash-chained audit log, learned policies, plus a measured eval score |
| **Microsoft** | The backend runs on **Azure Container Apps**, with **Application Insights** tracing and Log Analytics. **Azure AI Content Safety Prompt Shields** screens every vendor email for injected instructions. The agent model itself (Claude Haiku 4.5) is called through Anthropic's API, because Claude on Azure AI Foundry had no quota on our student subscription |
| **Bright Data** | Vendor identity checks from live public web data through the SERP API: the vendor's official phone numbers and website, compared with the phone on file and with any callback number in the email. Blocked or empty results escalate to a human instead of guessing |
| **Figma** | UI design for the work queue, approve/reject, and "why?" views |

## What makes it different

- **Limits enforced in code.** The demo attack email hides a prompt injection. Even if the model were fooled, the permission layer denies the action, and the denial is in the audit log.
- **A measured score.** We use 300 labeled emails across 31 scenarios, split into dev and holdout by vendor. Results are below.
- **A learned-policy loop.** One human correction becomes a proposed general policy, and a controller approves it.
- **Real data, fake money.** We verify real public companies (from SEC EDGAR) on the live web, but every invoice, bank account and email is fabricated. The eval vendors are fictional. No email impersonates a real company.

## Evaluation

The dataset (`data/v2/`, see `data/v2/DATASET_CARD.md`) has 300 emails: 140 fraud and 160 legit, 42% of them hard. Results are scored by `python -m vouch.eval`. The table compares the rule-based baseline (`RuleBasedAgent`, no LLM) with the Claude agent (`LLMAgent`, Claude Haiku 4.5) on the **holdout** set: 108 emails from vendors never used for tuning.

| Holdout (108 emails) | Rule-based baseline | Claude agent |
|---|---|---|
| Routed to the right lane (auto-clear / human / reject) | 70% | **90%** |
| Fraud auto-cleared (paid without a human) | 11 of 51 | **1 of 51** |
| Hard cases routed right (53) | 58% | **92%** |
| Fraud without a bank change routed right (22) | 36% | **82%** |
| Legitimate emails wrongly rejected | 0 of 57 | 0 of 57 |
| Routine legitimate invoices auto-cleared | 18 of 18 | 16 of 18 |
| Injected emails that changed anything | 0 | 0 |

- **Dev (192 emails):** lane accuracy goes from 71% to 90%, and fraud auto-cleared from 21 of 89 to 2 of 89.
- **Cost:** about $0.018 per email, about $5.50 for all 300.
- **Simulated web:** with the web check replayed on the fictional vendors (`--web sim`), holdout fraud auto-cleared is 0 of 51. The web check flagged 3 unlisted callback numbers, all on fraud emails, and none on legitimate ones.
- **Files:** `eval_results_v2.json` (baseline), `eval_results_v2_llm.json` (Claude agent), `eval_results_v2_llm_websim.json` (simulated web).
- **Tuning:** prompts and guards were tuned on dev only.

## Demo (3 minutes)

The demo runs in the web console, in the **Live demo** tab and the **Work queue** tab:

1. **Pick Attack 1 in Live demo:** a lookalike domain asks for a bank change, with a hidden HTML-comment injection. "Show what the AI receives" reveals the hidden text.
2. **Watch the pipeline:** each step lights up from the evidence the server actually recorded: Prompt Shields, email auth, domain check, web check, Claude's tool calls, the code guard, the policy lane and the gateway. The result is stamped **Blocked**, with $0 moved.
3. **Try to break it:** "Approve it anyway" and "Force the payment" send real requests. The server denies both, and the denials appear in red in the hash-chained audit trail.
4. **Pick Attack 2:** "An outsider says Motorola changed its bank". The email passes SPF, DKIM and DMARC, but Bright Data shows the callback number isn't one Motorola lists online.
5. **A normal invoice in the Work queue:** the evidence is all green, and the policy lane auto-cleared it.
6. **A human correction becomes a proposed policy.** Approve an item the agent called fraud, with a reason, then go to **Learned policies**, click "Draft from corrections", and approve it as the controller.
7. **"Why?"**: each item's audit trail, and "Why was this vendor's bank changed?".

## Team and ownership

| Person | Owns |
|---|---|
| **Ayushi** | Core system: tables, state machine, roles and `can()`, separation of duties, audit log and "why?" query, gateway, API, v2 dataset pipeline and eval, Azure deployment and tracing, UI wiring |
| **Sujith** | Agent and web intelligence: Claude agent loop and tools, Bright Data vendor verification, prompt-injection defense (incl. Azure Prompt Shields), learned-policy loop, agent evaluation runs |
| **Xanath** | Seed data and answer key, labeled eval set, Figma UI design, demo script and pitch, Devpost submission, sponsor liaison |

## Repository layout

```
vouch/            core system and agent (Python)
  core.py           state machine, can(), audit log, policy lane, "why?"
  db.py             SQLite schema and integrity triggers
  gateway.py        the only code that pays or changes bank details
  api.py            FastAPI: items, audit, vendors, policies, demo endpoints, serves the console
  llm_agent.py      Claude agent: tools, prompt, injection defence, code guards
  prompt_shields.py Azure AI Content Safety Prompt Shields
  web_verify.py     Bright Data vendor web verification
  learned_policy.py human correction -> proposed policy -> controller
  eval.py, run_pipeline.py, seed.py, demo.py, web_sim.py
ui/               web console (plain HTML/CSS/JS, no build step), served at /ui/
data/v2/          the 300-email dataset, vendors, payments, email history, demo companies
tests/            pytest suite
scripts/          dataset builders, demo and recording scripts
deploy/           Azure deployment notes (AZURE_DEPLOYED.md)
```

## Setup

```bash
git clone https://github.com/sujith2511/Vouch-AP-Fraud-and-Bank-Change-Guard.git
cd Vouch-AP-Fraud-and-Bank-Change-Guard
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                       # full test suite, no network or API keys needed
```

Optional keys go in `.env`. Everything works without them, but falls back to the rule-based agent and recorded web data.
```
ANTHROPIC_API_KEY=...                  # Claude agent and policy drafting
VOUCH_MODEL=claude-haiku-4-5
AZURE_CONTENT_SAFETY_ENDPOINT=...      # Prompt Shields
AZURE_CONTENT_SAFETY_KEY=...
BRIGHT_DATA_API_KEY=...                # live web verification
BRIGHT_DATA_SERP_ZONE=...
```

To run the console locally with the dataset, using the dev keys (`dev-accountant-key`, `dev-accountant2-key`, `dev-controller-key`, …):
```bash
.venv/bin/python -m vouch.run_pipeline --dataset v2 --db vouch.db            # seed + rule-based agent (free)
VOUCH_DB=vouch.db .venv/bin/uvicorn vouch.api:app --port 8000                # open http://localhost:8000
```

To score the Claude agent (300 emails, about $5.50):
```bash
.venv/bin/python -m vouch.run_pipeline --dataset v2 --agent vouch.llm_agent:LLMAgent --db run.db
.venv/bin/python -m vouch.eval --db run.db
```

Deployment is described in `DEPLOY.md` and `deploy/AZURE_DEPLOYED.md`. Never commit real API keys: `.env` and `deploy/*.local.json` are gitignored.

## Known limitations

- All invoices, emails and bank details are synthetic. Only the demo companies' public names, websites and phone numbers are real.
- There is no real email inbox or bank integration. The demo buttons inject messages, and the gateway's payment rail is a database record.
- Detection combines a small set of signals with an LLM's judgment. It is not a trained fraud model. The dataset's easy cases are easy for simple models, so hard-case results matter most.
- SQLite with a single replica. On Azure Files it uses lock-file locking. A real deployment would move to Azure SQL or Postgres.
- The Claude agent errs on the side of caution, so some legitimate mail goes to a human that the rules alone would auto-clear.

## Acknowledgements

Built for CalHacks 13. Thanks to Hyphenate, Microsoft, Bright Data and Figma for the tools, credits and mentorship.
