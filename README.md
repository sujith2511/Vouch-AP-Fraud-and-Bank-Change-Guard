# Vouch: an AP agent that can't be talked into paying

Built at CalHacks 13 by Ayushi, Sujith and Xanath.

Vouch is an accounts-payable agent that investigates vendor "we changed our bank account" emails. It can never move money itself. Only a code-enforced gateway can, and only after a human approves.

> Status: hackathon build. Items marked **(planned)** or **TODO** are not final until the team fills them in.

## The problem

In bank-change fraud (business email compromise), an attacker emails a company pretending to be a real vendor and asks that future payments go to a new bank account. A busy AP clerk updates the vendor record, and the next invoice goes to the attacker. It is common, costly, and hard to catch by eye.

## What Vouch does

1. **Reads** vendor emails and invoices and extracts the claim: sender, new bank details, amount.
2. **Investigates** using payment history, sender domain, amount patterns, and live public web data about the real vendor.
3. **Proposes** a verdict with reasons, and asks a human to confirm, for example by calling the phone number on the vendor's real website.
4. **Records** every step, including denied attempts, in an append-only audit log, so "why?" is one query.
5. **Learns**: when a human corrects a verdict, the agent proposes a general policy that a controller must approve.

## How it works

Every vendor email becomes a work item that moves through fixed states. Each move is checked by code, not by the prompt.

```
NEW -> PROPOSED -> APPROVED -> POSTED
          |  ^
          v  |
       NEEDS_INFO
```

| State | Who moves it | Meaning |
|---|---|---|
| NEW | Sync job | A vendor email arrived |
| PROPOSED | AI agent | Agent investigated and wrote a verdict with evidence |
| NEEDS_INFO | AI agent | Agent asked a human to verify (for example, a callback); the answer returns the item to PROPOSED |
| APPROVED | Human accountant | A human decided. The agent cannot approve its own proposal |
| POSTED | Gateway only | The only step that changes the vendor record or releases a payment |

### Who may do what

| Actor | Allowed |
|---|---|
| Sync job | Create a work item |
| AI agent | Propose, ask, propose a policy |
| Accountant | Answer, approve or reject items |
| Controller | Approve policies |
| Gateway | Post. The only actor that can write to the record |

Separation of duties is enforced in code: whoever proposed an item cannot approve it.

### Audit log

Every transition is appended in the same commit as the change: time, actor, action, diff, reason, and evidence. Denied attempts are logged too. Asking "why was this vendor's bank changed?" is a single query.

```sql
SELECT at, actor, change, why
FROM audit_log
WHERE subject = '<work item id>'
ORDER BY at;
```

## Sponsors and where we use them

| Sponsor | Where it is used in Vouch |
|---|---|
| **Hyphenate** | The architecture: work-item state machine, role permissions in code, append-only audit log, learned policies, plus an eval score |
| **Microsoft** | Agent runs on Azure (Azure OpenAI or AI Foundry) and the backend is deployed on Azure. Prompt-injection protection on untrusted vendor emails, tracing and logging, and a labeled eval set |
| **Bright Data** | Vendor identity verification from live public web data: the vendor's official phone number, public business listings, name matching. Blocked or empty results escalate to a human instead of guessing |
| **Apify** | A separate fraud-signal source: an Actor that searches for reports of the vendor or domain being impersonated. Also the fallback when Bright Data is blocked |
| **Figma** | UI design for the work queue, approve/reject, and "why?" views |
| **Coinbase (planned, stretch)** | Gateway pays via x402 or the Wallet MCP on testnet only, with per-payment and daily caps; it refuses flagged or over-cap payments |

## What makes it different

- **Limits enforced in code.** The demo email contains a hidden prompt-injection line. Even if the model were fooled, the permission layer denies the action.
- **A measured score.** About 20 labeled emails (real, fake, ambiguous), reported as fraud caught and false blocks.
- **A learned-policy loop.** One human correction becomes a proposed general policy.
- **Real data, fake money.** We verify real public vendors with live web data, but invoices and the attack email are fabricated, using an invented lookalike domain. No real company is impersonated.

## Demo (3 minutes)

1. A normal invoice resolves smoothly end to end.
2. Fire a spoofed "we changed banks" email live.
3. The agent flags it within seconds, with reasons and live web evidence.
4. The agent's attempt to approve or pay is denied by the code.
5. A human correction becomes a proposed policy.
6. Run the "why?" query on the audit log.

## Team and ownership

| Person | Owns |
|---|---|
| **Ayushi** | Core system: tables, state machine, roles and `can()`, separation of duties, audit log and "why?" query, gateway, API, Azure deployment and tracing, UI wiring, Coinbase gateway if time allows |
| **Sujith** | Agent and web intelligence: agent loop and tools on Azure OpenAI or AI Foundry, Bright Data vendor verification, Apify impersonation search and fallback, prompt-injection defense, learned-policy loop, eval runner |
| **Xanath** | Seed data and answer key, labeled eval set, Figma UI design, demo script and pitch, Devpost submission, sponsor liaison |

## Agent tools

| Tool | Purpose |
|---|---|
| `read_vendor_history` | Payment and bank-change history for a vendor |
| `check_domain` | Sender domain age, lookalike check, match to known contacts |
| `compare_amounts` | Is the invoice or request out of pattern for this vendor |
| `verify_vendor_web` | Bright Data: official phone, business listing, name match |
| `propose_verdict` | Write a verdict with reasons and evidence (moves item to PROPOSED) |
| `ask_human` | Ask for verification (moves item to NEEDS_INFO) |

## Repository layout (TODO: update to match the real structure)

```
/backend     state machine, roles, audit log, gateway, API
/agent       agent loop, tools, injection defense, policy learning
/data        seed vendors, payment history, emails, labeled eval set
/ui          work queue, approve/reject, "why?" view
/docs        demo script, design files
```

## Setup (TODO: fill in once the stack is final)

```bash
# 1. Clone the repo
git clone <repo-url>
cd vouch

# 2. Configure environment variables (names are placeholders)
cp .env.example .env
#   AZURE_OPENAI_ENDPOINT=
#   AZURE_OPENAI_API_KEY=
#   BRIGHT_DATA_API_KEY=
#   APIFY_API_TOKEN=

# 3. Install and run
# TODO: backend, agent, and UI start commands
```

Never commit real API keys. Use testnet only for any Coinbase integration.

## Evaluation

The eval set is about 20 labeled cases (real, fraudulent, ambiguous) with expected verdicts.

| Metric | Result |
|---|---|
| Fraud cases caught | TODO |
| Legitimate requests wrongly blocked | TODO |
| Cases escalated to a human | TODO |

## Known limitations

- All invoices, emails, and bank details are synthetic. Only vendor website lookups use real public data.
- No real email inbox or bank integration; a "send attack email" button injects messages for the demo.
- Detection uses a small set of signals chosen for depth, not a trained fraud model.

## Acknowledgements

Built for CalHacks 13. Thanks to Hyphenate, Microsoft, Bright Data, Apify, Figma and Coinbase for the tools, credits and mentorship.
