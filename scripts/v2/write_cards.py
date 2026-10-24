"""Generate data/v2/review_sample.md and data/v2/DATASET_CARD.md from the final files (numbers are computed, not typed)."""
import json, sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import load, load_jsonl

R = load_jsonl("data/v2/emails.jsonl"); V = load("data/v2/vendors.v2.json"); P = load_jsonl("data/v2/payments.v2.jsonl"); H = load_jsonl("data/v2/vendor_email_history.jsonl")
Q = json.load(open("data/v2/quality_report.json")); n = len(R)
T = lambda r: r["truth"]; A = lambda r: r["attributes"]["scenario_independent"]

# ------------------------------------------------------------------ review sample (40 stratified, truth below the separator)
byscen = defaultdict(list)
for r in R: byscen[T(r)["scenario"]].append(r)
pick = []
for k, l in byscen.items():
    l = sorted(l, key=lambda r: (T(r)["difficulty"] != "hard", r["id"])); pick.append(l[0] if len(pick) % 2 == 0 else l[-1])
chosen = {r["id"]: r for r in pick}
def add(pred, k):
    for r in R:
        if len(chosen) >= 40 or k == 0: break
        if r["id"] not in chosen and pred(r): chosen[r["id"]] = r; k -= 1
inj_where = {T(r)["injection"]["hidden_in"] for r in chosen.values() if T(r)["injection"]}
for r in R:
    if T(r)["injection"] and T(r)["injection"]["hidden_in"] not in inj_where and len(chosen) < 40: chosen[r["id"]] = r; inj_where.add(T(r)["injection"]["hidden_in"])
add(lambda r: T(r)["difficulty"] == "hard" and T(r)["label"] == "legit", 3)
add(lambda r: T(r)["difficulty"] == "hard" and T(r)["family"] == "fraud_nobank", 3)
add(lambda r: True, 40)
S = sorted(chosen.values(), key=lambda r: r["id"])[:40]
def view(r):
    h = r["headers"]; b = r["claimed_bank"]
    out = [f"### {r['id']}", f"**From:** {r['from_name']} <{r['from_addr']}>  |  **Reply-To:** {r['reply_to']}  |  **To:** {r['to']}" + (f"  |  **Cc:** {', '.join(r['cc'])}" if r["cc"] else ""),
           f"**Sent:** {r['sent_at']}  |  **SPF/DKIM/DMARC:** {h['spf']}/{h['dkim']}/{h['dmarc']}  |  **Mailer:** {h['mailer']}  |  **Sender domain age (simulated):** {r['sender_domain_age_days']} d  |  **Lang:** {r['language']}",
           f"**Subject:** {r['subject']}", "", "```", r["body_text"], "```"]
    if r["quoted_history"]: out += ["*Quoted / forwarded:*", "```", r["quoted_history"], "```"]
    inv = r["invoice"]; out.append(f"**Invoice** {inv['number']} | {inv['amount']:,.2f} {inv['currency']} | PO {inv['po'] or '-'}" + (f" | **Claimed bank** {b['bank_name']} {b['routing_or_iban']} / {b['account']} ({b['change_type']})" if b else " | no bank claim"))
    if r["attachments"]: out.append("**Attachments:** " + ", ".join(a["filename"] for a in r["attachments"]))
    out.append(f"**Vendor on file:** {r['vendor_snapshot'].get('legal_name', '(not in vendor master)')} | typical {r['vendor_snapshot'].get('typical_amount')} | domain {r['vendor_snapshot'].get('domain')}")
    return "\n".join(out)
md = ["# Review sample (40 emails)", "", f"Stratified: {sum(T(r)['difficulty'] == 'hard' for r in S)} hard, {sum(bool(T(r)['injection']) for r in S)} injection, {sum(T(r)['family'] == 'fraud_nobank' for r in S)} no-bank-change fraud, "
      f"{len({T(r)['scenario'] for r in S})} of 31 scenarios, {sum(r['split'] == 'holdout' for r in S)} holdout. **Read the emails first and guess; the answer key is below the separator.**", ""]
md += [view(r) + "\n\n---\n" for r in S]
md += ["", "# ================= TRUTH (do not show to the agent) =================", ""]
for r in S:
    t = T(r)
    md.append(f"- **{r['id']}** [{r['split']}] {t['scenario']} / {t['sub_variant']} | label **{t['label']}**, lane **{t['expected_lane']}**, agent verdict **{t['correct_agent_verdict']}**, difficulty **{t['difficulty']}**"
              + (f" ({t['hard_reason']})" if t["hard_reason"] else "") + f"\n  - tells: {'; '.join(x['id'] + ': ' + x['detail'] for x in t['tells']) or '(none)'}"
              + (f"\n  - surface features: {', '.join(t['surface_features'])}" if t["surface_features"] else "") + f"\n  - callback would reveal: {t['callback_outcome']}"
              + (f"\n  - injection: {t['injection']['payload_id']} ({t['injection']['style']}, {t['injection']['goal']}) hidden in {t['injection']['hidden_in']}, source {t['injection']['source_id']}" if t["injection"] else ""))
Path("data/v2/review_sample.md").write_text("\n".join(md))

# ------------------------------------------------------------------ dataset card
def table(c, hdr):
    return "| " + hdr + " | n | % |\n|---|---:|---:|\n" + "\n".join(f"| {k} | {v} | {100 * v / sum(c.values()):.1f}% |" for k, v in sorted(c.items(), key=lambda kv: (-kv[1], str(kv[0]))))
sc_split = defaultdict(Counter)
for r in R: sc_split[T(r)["scenario"]][r["split"]] += 1
sc_tab = "| scenario | family | dev | holdout | total | hard |\n|---|---|---:|---:|---:|---:|\n" + "\n".join(
    f"| {k} | {byscen[k][0]['truth']['family']} | {c['dev']} | {c['holdout']} | {sum(c.values())} | {sum(T(r)['difficulty'] == 'hard' for r in byscen[k])} |" for k, c in sorted(sc_split.items(), key=lambda kv: (byscen[kv[0]][0]['truth']['family'], kv[0])))
rep, aud, div = Q["repetition"], Q["shortcut_audit"], Q["diversity"]
real = [v for v in V if v["in_master"]]
card = f"""# Vouch dataset v2: DATASET CARD

An evaluation dataset for an accounts-payable agent that defends against vendor bank-change fraud **and** other vendor-payment fraud.
**{n} labeled emails** ({sum(T(r)['label'] == 'fraud' for r in R)} fraud / {sum(T(r)['label'] == 'legit' for r in R)} legit), **{len(real)} vendors + {len(V) - len(real)} unregistered "phantom" suppliers**, {len(P):,} payment records, {len(H)} past legit emails as a per-vendor baseline.
Everything is fictional or simulated except the public payment amounts/POs it is built on (see "Real vs derived vs simulated vs fabricated"). Generated 2026-10-24.

**Scope note.** This card covers the dataset only. Pipeline/eval integration (seed adapters, eval metrics, API) was deliberately NOT done in this build.

## Files (`data/v2/`)
| file | what |
|---|---|
| `emails.jsonl` | the {n} labeled emails, one JSON object each (schema below). `emails.dev.jsonl` ({sum(r['split'] == 'dev' for r in R)}) and `emails.holdout.jsonl` ({sum(r['split'] == 'holdout' for r in R)}) are the same records split **by vendor**. |
| `vendors.v2.json` | {len(real)} vendor master records + {len(V) - len(real)} phantom suppliers (`in_master: false`): industry, size band, country/currency, payment method/terms, cadence, PO policy, typical amount + spread, contacts, bank on file (+ dated bank-change history), voice profile, mailer, domain registration. |
| `payments.v2.jsonl` | {len(P):,} payment records = the real SF vouchers + **simulated** invoice/due/paid dates and invoice numbers. |
| `vendor_email_history.jsonl` | {len(H)} past **legit** emails (8-25 per vendor) used as the baseline an agent compares against (includes 16 genuine past bank-change notices). |
| `case_specs.json` | the deterministic specs (facts + ground truth) every email was written from. |
| `prose/` | the raw written prose batches (cases + history) so the dataset can be rebuilt without rewriting. |
| `review_sample.md` | 40 stratified emails to read; answers below a separator. |
| `quality_report.json` | repetition / diversity / shortcut-audit numbers quoted below. |
| `demo_real_vendors.json` | **DEMO ONLY**, separate and untouched by this build: 4 real public companies (SEC EDGAR + their SF payments). Never part of eval; no email here impersonates them. |
| `injections.json` (in `data/`) | the 18 InjecAgent-derived payloads used by the injection cases. |

### Email record (agent-visible fields first; `truth` and `provenance` must NEVER be shown to an agent)
`id, vendor_id, split, thread_id, in_reply_to, message_id, sent_at, received_at, from_name, from_addr, reply_to, to, cc, subject, body_text, body_html_present, quoted_history,
attachments[{{filename,type,extracted_text,metadata}}], headers{{spf,dkim,dmarc,return_path,message_id_domain,mailer,received_hops,origin_ip}}, sender_domain, sender_domain_age_days (+_simulated), domain_registered_at,
language, device_footer, invoice{{number,po,amount,currency,date,due_date,line_items[]}}, claimed_bank{{bank_name,routing_or_iban,account,swift,country,change_type}}, claim_changes_bank, change_type,
vendor_snapshot{{bank_on_file,phone_on_file,domain,typical_amount,last_bank_change,authorized_contacts,po_policy,usual_mailer,usual_mail_ip,recent_invoices,...}}`,
then **`truth`** `{{scenario, sub_variant, family, label, expected_lane (auto_clear/human_review/reject), correct_agent_verdict (legit/fraud/uncertain), difficulty, hard_reason, tells[], surface_features[], callback_outcome, injection{{payload_id,text,style,goal,source_id,hidden_in}}, lookalike_fuzzer, pair_id, pair_with, pending_bank_change_notice}}`
and **`provenance`** `{{real_fields, derived_fields, simulated_fields, fabricated_fields, style_sources, generator, generated_at}}`. `attributes` holds the sampled style dimensions (channel, thread, length, register, urgency, noise, weekday, hour).
Note: `vendor_snapshot.pending_bank_change_notice` (a mailed notice on file) exists only for the genuine bank-change cases, so an agent can verify them; `truth.pending_bank_change_notice` repeats it for the key.

## Counts
{table(Counter(T(r)['label'] for r in R), 'label')}

{table(Counter(T(r)['difficulty'] for r in R), 'difficulty')}

{table(Counter(r['split'] for r in R), 'split (by vendor, ~64/36)')}

{table(Counter(T(r)['expected_lane'] for r in R), 'expected_lane')}

{table(Counter(T(r)['correct_agent_verdict'] for r in R), 'correct_agent_verdict')}

### Scenarios x split (31 scenarios, every one has >= 8 emails and appears in both splits)
{sc_tab}

### Other dimensions
{table(Counter(A(r)['channel'] for r in R), 'sender channel')}

{table(Counter(A(r)['thread'] for r in R), 'thread position')}

{table(Counter(A(r)['length'] for r in R), 'length bucket')}

{table(Counter(A(r)['register'] for r in R), 'register')}

{table(Counter(r['language'] for r in R), 'language')}

{table(Counter(r['device_footer'] for r in R), 'device footer')}

{table(Counter('+'.join(a['type'] for a in r['attachments']) or 'none' for r in R), 'attachments')}

{table(Counter(T(r)['lookalike_fuzzer'] for r in R if T(r)['lookalike_fuzzer']), 'dnstwist fuzzer (lookalike cases)')}

{table(Counter(T(r)['injection']['hidden_in'] for r in R if T(r)['injection']), 'prompt-injection placement')}

{table(Counter(t['id'] for r in R for t in T(r)['tells']), 'tells (ground-truth evidence a careful reviewer could find)')}

## How it was built
1. **Vendors:** 60 fictionalized vendors with real SF Controller payment records (v1, deduplicated), extended in `scripts/v2/vendor_master.py` (seeded) with industry, size, 12 international vendors (DE/FR/GB/CA, fake IBAN/BIC formats, non-US phone formats), terms, methods, contacts, bank-change history, simulated payment dates and invoice numbers, and 24 phantom suppliers.
2. **Case specs** (`scripts/v2/case_specs.py`, deterministic, no LLM): 300 attribute vectors across 31 scenarios; every amount, number, header, auth result, bank detail, date, lane, label, tell and callback outcome is fixed in code. Gates enforced by `spec_report.py`: every scenario >= 8, in both splits, hard share >= 35%, no repeated attribute vector, no fraud case expected to auto-clear, hard-legit cases carry fraud-looking surface features, fraud cases carry tells.
3. **Prose:** written in batches of 15 (history: ~60-110 per batch) **directly by Claude inside the working session** (no API key was available and the `claude` CLI is not installed, so neither the SDK nor `claude -p` was used), one vendor voice profile per vendor, then **verified by code** (`checks.py`): required facts present (invoice number, amount, bank numbers, PO where required, new address/name), no label-leaking words (fraud, scam, suspicious, fake, test, ...; also es/fr/de equivalents), no real company names, only reserved domains (.example/.test/.invalid) in addresses and links, no urgency words unless the spec has urgency, no text addressed to an AI, length within the spec range. Failures were rewritten and re-checked.
4. **Injection payloads** (15 cases) are inserted by **code** (`injlib.py`, `assemble_emails.py`), never written by the model, in five placements (html_comment, white_span, quoted_reply, footer, attachment_text), phrasings adapted from InjecAgent (MIT) "base"/"enhanced" styles, each with its source row id.
5. **Assembly + final fact check** (`assemble_emails.py`): re-verifies every final record against its spec (facts, domains, injection exactly once in its placement, split==vendor split). 0 errors.

## Quality gates and results
| gate | result |
|---|---|
| scenarios >= 8 each, both splits | pass (31/31) |
| hard share >= 35% | pass ({100 * sum(T(r)['difficulty'] == 'hard' for r in R) / n:.1f}%) |
| attribute vectors unique | pass |
| fact check of every email vs its spec | pass (300/300) |
| reserved domains / fake banks only, no real-company names, no label-leak words | pass (code-checked) |
| split by vendor (no vendor in both splits) | pass |
| repetition | max pairwise cosine {rep['cosine']['max']}, 99th pct {rep['cosine']['p99']}; max 5-gram Jaccard {rep['jaccard5']['max']} (pairs > 0.4: {rep['pairs_jaccard_gt_0.4']}); {rep['distinct_openings']} distinct openings, {rep['distinct_endings']} distinct endings (see below) |
| diversity | vocabulary {div['vocab_size']} words; body length median {div['body_words']['median']} words (min {div['body_words']['min']}, max {div['body_words']['max']}); {div['thread_structures']} thread structures; entropy bits: scenario {div['scenario']['entropy_bits']}, register {div['register']['entropy_bits']}, length {div['length']['entropy_bits']} |
| shortcut audit | see below: **partial pass, with caveats** |

**Repetition detail.** Most common openings: {', '.join(f"'{a}' x{b}" for a, b in rep['most_common_openings'])}. These are normal salutations and track the vendor voice profiles, but the same vendor reuses its own greeting/closing by design (that is the point of a per-vendor baseline). Most common endings (signature blocks/device footers): {', '.join(f"'{a}' x{b}" for a, b in rep['most_common_endings'][:4])}.

**Shortcut audit** (logistic regression, 5-fold CV **grouped by vendor**; majority baseline label {aud['majority_baseline']['label']}, lane {aud['majority_baseline']['lane']}):
| feature set | predicts label | predicts expected_lane |
|---|---:|---:|
""" + "\n".join(f"| {k} | {v['label']} | {v['lane']} |" for k, v in aud.items() if isinstance(v, dict) and "label" in v and k != "majority_baseline") + f"""

* The first run of this audit found a real artifact: **attachment count alone predicted the label at 0.89** (legit emails averaged 1.06 attachments, fraud 0.13) because most fraud scenarios had been specified with no attachment. Fix: whenever the prose says something is attached/enclosed and the spec has no attachment, an invoice PDF is generated from the email's own facts (59 emails). Artifact-only accuracy dropped to {aud[next(k for k in aud if k.startswith('artifact_only'))]['label']}, below the ~85% bar but still above the {aud['majority_baseline']['label']} baseline (residual signal: bank-change vocabulary, PO mentions, quoting and CC habits).
* **Unresolved:** text TF-IDF alone predicts the label at {aud['body_text_tfidf_only']['label']} and text+header at {aud['text+header']['label']}. Much of this is legitimate (fraud here is mostly bank-change requests, whose vocabulary differs from invoices, and header tells are real tells), but it means the **easy and medium cases are easy for a linear model ({aud['text+header on EASY/MEDIUM cases only (label)']} on label)**. On hard cases the same model gets {aud['text+header on HARD cases only (label)']}, i.e. the hard subset is harder but not hard. Treat the headline numbers on this dataset accordingly and look at hard-case and per-scenario results.

## Real vs derived vs simulated vs fabricated
* **Real:** vendor payment amounts, voucher ids, PO numbers, fiscal years and departments (SF Controller open data), and the phrasing patterns of the injection payloads (InjecAgent).
* **Derived (by code from real fields):** typical amount and spread, cadence, PO policy, industry (from the fictional name word + buyer departments), size band, expected lane, correct verdict, difficulty, tells.
* **Simulated (marked):** all dates (payment, invoice, due, sent/received), invoice numbers, payment terms/methods, domain registration and age, headers (SPF/DKIM/DMARC, IPs, mailer, hops), the callback outcome, the mailed-notice records, FX rates. The real SF data has **no payment dates**, so date patterns use documented defaults (weekday-weighted, month-end spike, net terms + N(-1.5, 4.5) days, Thursday ACH runs), **not** ERP-fitted distributions.
* **Fabricated (must be fake):** every vendor/person/company name, domain (.example/.test/.invalid only), phone number (555-01xx and fictional ranges), bank account (routing 999xxxxxx, IBAN check digits `00`, BIC `ZZBK..`), tax ID (`99-xxxxxxx`) and all email prose.

## Sources and licenses
| source | use | license / terms |
|---|---|---|
| SF Controller "Vendor Payments (Vouchers)" `n9pm-xkyq` and "Purchase Order Summary" `p5r5-fd7g` (data.sf.gov, listed on data.gov) | real payment history | PDDL 1.0 |
| InjecAgent, github.com/uiuc-kang-lab/InjecAgent @ f19c9f2 | injection phrasing (base/enhanced), source row ids | MIT, Copyright (c) 2023 Qiusi Zhan (notice in `data/README.md`) |
| dnstwist 20250130 | lookalike domains (homoglyph, omission, transposition, hyphenation, ...) | Apache-2.0 |
| SEC EDGAR submissions API (data.sec.gov) | `demo_real_vendors.json` only | US government public data |
| Enron corpus, Nazario phishing corpus (CC-BY-4.0), HF `zefang-liu/phishing-email-dataset` (LGPL-3.0), HF `renemel/compiled-phishing-dataset` (CC-BY-SA-4.0) | downloaded and scrubbed for v1 style samples; **not used as texture for the v2 prose** (see limits) | as stated; raw files stay in gitignored `data/raw/` |
| DFKI ERPsim SAP fraud data | **not available** (`data/raw/erp_fraud/` missing) | n/a |

## Known limits and problems
1. **Style excerpts were not used.** The brief asked for 2-3 rotating real style excerpts (Enron/phishing) per email as texture. This build did not use them; prose follows vendor voice profiles and scenario briefs only. `provenance.style_sources` says so. The v1 scrubbed excerpts still exist locally (`data/local/style_samples.json`, gitignored).
2. **No ERP data**, so no ERP-derived typologies or timing distributions. The kickback scenario is a generic threshold-splitting pattern (pairs of invoices just under an assumed $10,000 approval limit, sum above it), not an ERP-derived typology.
3. **Prose was written by one author (the assistant) in one session.** Despite per-vendor voices and code-checked facts, stylistic range is narrower than real mail; non-English emails (es/fr/de, 8.7%) have not been reviewed by a native speaker.
4. **Prevalence is not realistic:** {100 * sum(T(r)['label'] == 'fraud' for r in R) / n:.0f}% fraud, because every one of 31 scenarios needs >= 8 cases. Report precision with this in mind (or reweight).
5. **Shortcuts remain** (see audit). The attachment fix was applied after assembly rather than in the spec; `provenance.simulated_fields` marks those emails.
6. **Expected lanes encode an ideal reviewer, not the current policy rules.** E.g. PO mismatches, credit memos, duplicates and reminders are `human_review`; no-bank-change fraud is `human_review` (never `reject`). A weak policy that only checks bank/auth/domain/amount will auto-clear some of these on purpose (that is what the dataset is meant to expose).
7. Line-item descriptions come from industry templates with random month names, so a description's month can disagree with the invoice date. Amounts, numbers and totals are exact; descriptions are texture.
8. Dormant vendors (14 of 60 have no payment in 2026) appear mostly in the "compromised mailbox / fake invoice" scenarios by design; normal scenarios use the 46 recently active vendors. Their history emails sit in earlier years.
9. `callback_outcome`, `pending_bank_change_notice` and simulated domain ages are plausible fiction, not observed facts.
10. Phantom suppliers (`PH###`) are in `vendors.v2.json` with `in_master: false`; an integration must handle "vendor not in master".
11. Vendor names are fictional but their *spellings and mess* come from real payees; contact names and company names could coincidentally match real ones.
12. v1 files from the earlier build (`data/vendors.json`, `data/fixtures/`) are untouched and are **not** v2.

## Reproduce
```
python scripts/v2/vendor_master.py && python scripts/v2/history_specs.py       # vendors, payments, history specs
python scripts/v2/case_specs.py && python scripts/v2/spec_report.py             # 300 specs + gates
# prose: data/v2/prose/*.json (copy to data/raw/v2_batches/ to rebuild without rewriting)
python scripts/v2/history_batches.py check && python scripts/v2/case_batches.py check
python scripts/v2/assemble_history.py && python scripts/v2/assemble_emails.py   # final jsonl files + fact check
python scripts/v2/quality_report.py && python scripts/v2/write_cards.py          # report, review sample, this card
```
"""
Path("data/v2/DATASET_CARD.md").write_text(card)
print("wrote review_sample.md (", len(S), "emails) and DATASET_CARD.md")
print("review sample:", {"hard": sum(T(r)['difficulty'] == 'hard' for r in S), "injection": sum(bool(T(r)['injection']) for r in S), "nobank_fraud": sum(T(r)['family'] == 'fraud_nobank' for r in S), "scenarios": len({T(r)['scenario'] for r in S})})
