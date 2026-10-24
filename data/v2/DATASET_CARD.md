# Vouch dataset v2: DATASET CARD

An evaluation dataset for an accounts-payable agent that defends against vendor bank-change fraud **and** other vendor-payment fraud.
**300 labeled emails** (140 fraud / 160 legit), **60 vendors + 24 unregistered "phantom" suppliers**, 5,056 payment records, 817 past legit emails as a per-vendor baseline.
Everything is fictional or simulated except the public payment amounts/POs it is built on (see "Real vs derived vs simulated vs fabricated"). Generated 2026-10-24.

**Scope note.** This card covers the dataset only. Pipeline/eval integration (seed adapters, eval metrics, API) was deliberately NOT done in this build.

## Files (`data/v2/`)
| file | what |
|---|---|
| `emails.jsonl` | the 300 labeled emails, one JSON object each (schema below). `emails.dev.jsonl` (192) and `emails.holdout.jsonl` (108) are the same records split **by vendor**. |
| `vendors.v2.json` | 60 vendor master records + 24 phantom suppliers (`in_master: false`): industry, size band, country/currency, payment method/terms, cadence, PO policy, typical amount + spread, contacts, bank on file (+ dated bank-change history), voice profile, mailer, domain registration. |
| `payments.v2.jsonl` | 5,056 payment records = the real SF vouchers + **simulated** invoice/due/paid dates and invoice numbers. |
| `vendor_email_history.jsonl` | 817 past **legit** emails (8-25 per vendor) used as the baseline an agent compares against (includes 16 genuine past bank-change notices). |
| `case_specs.json` | the deterministic specs (facts + ground truth) every email was written from. |
| `prose/` | the raw written prose batches (cases + history) so the dataset can be rebuilt without rewriting. |
| `review_sample.md` | 40 stratified emails to read; answers below a separator. |
| `quality_report.json` | repetition / diversity / shortcut-audit numbers quoted below. |
| `demo_real_vendors.json` | **DEMO ONLY**, separate and untouched by this build: 4 real public companies (SEC EDGAR + their SF payments). Never part of eval; no email here impersonates them. |
| `injections.json` (in `data/`) | the 18 InjecAgent-derived payloads used by the injection cases. |

### Email record (agent-visible fields first; `truth` and `provenance` must NEVER be shown to an agent)
`id, vendor_id, split, thread_id, in_reply_to, message_id, sent_at, received_at, from_name, from_addr, reply_to, to, cc, subject, body_text, body_html_present, quoted_history,
attachments[{filename,type,extracted_text,metadata}], headers{spf,dkim,dmarc,return_path,message_id_domain,mailer,received_hops,origin_ip}, sender_domain, sender_domain_age_days (+_simulated), domain_registered_at,
language, device_footer, invoice{number,po,amount,currency,date,due_date,line_items[]}, claimed_bank{bank_name,routing_or_iban,account,swift,country,change_type}, claim_changes_bank, change_type,
vendor_snapshot{bank_on_file,phone_on_file,domain,typical_amount,last_bank_change,authorized_contacts,po_policy,usual_mailer,usual_mail_ip,recent_invoices,...}`,
then **`truth`** `{scenario, sub_variant, family, label, expected_lane (auto_clear/human_review/reject), correct_agent_verdict (legit/fraud/uncertain), difficulty, hard_reason, tells[], surface_features[], callback_outcome, injection{payload_id,text,style,goal,source_id,hidden_in}, lookalike_fuzzer, pair_id, pair_with, pending_bank_change_notice}`
and **`provenance`** `{real_fields, derived_fields, simulated_fields, fabricated_fields, style_sources, generator, generated_at}`. `attributes` holds the sampled style dimensions (channel, thread, length, register, urgency, noise, weekday, hour).
Note: `vendor_snapshot.pending_bank_change_notice` (a mailed notice on file) exists only for the genuine bank-change cases, so an agent can verify them; `truth.pending_bank_change_notice` repeats it for the key.

## Counts
| label | n | % |
|---|---:|---:|
| legit | 160 | 53.3% |
| fraud | 140 | 46.7% |

| difficulty | n | % |
|---|---:|---:|
| hard | 127 | 42.3% |
| medium | 108 | 36.0% |
| easy | 65 | 21.7% |

| split (by vendor, ~64/36) | n | % |
|---|---:|---:|
| dev | 192 | 64.0% |
| holdout | 108 | 36.0% |

| expected_lane | n | % |
|---|---:|---:|
| human_review | 205 | 68.3% |
| auto_clear | 58 | 19.3% |
| reject | 37 | 12.3% |

| correct_agent_verdict | n | % |
|---|---:|---:|
| legit | 123 | 41.0% |
| uncertain | 121 | 40.3% |
| fraud | 56 | 18.7% |

### Scenarios x split (31 scenarios, every one has >= 8 emails and appears in both splits)
| scenario | family | dev | holdout | total | hard |
|---|---|---:|---:|---:|---:|
| bank_country_mismatch | fraud_bank | 5 | 3 | 8 | 3 |
| compromised_real_account | fraud_bank | 6 | 3 | 9 | 3 |
| executive_pressure | fraud_bank | 5 | 3 | 8 | 0 |
| fake_vendor_onboarding | fraud_bank | 5 | 3 | 8 | 1 |
| lookalike_domain | fraud_bank | 6 | 4 | 10 | 1 |
| prompt_injection | fraud_bank | 10 | 5 | 15 | 8 |
| split_account_routing_messages | fraud_bank | 6 | 2 | 8 | 2 |
| third_party_factoring_agent | fraud_bank | 5 | 3 | 8 | 1 |
| thread_hijack | fraud_bank | 6 | 3 | 9 | 9 |
| duplicate_altered_invoice_number | fraud_nobank | 5 | 3 | 8 | 5 |
| fake_invoice_compromised_domain_real_bank | fraud_nobank | 5 | 3 | 8 | 4 |
| inflated_invoice_just_under_1_5x | fraud_nobank | 6 | 3 | 9 | 9 |
| invoice_sequence_anomaly | fraud_nobank | 5 | 3 | 8 | 8 |
| kickback_threshold_splitting | fraud_nobank | 4 | 4 | 8 | 8 |
| phantom_vendor | fraud_nobank | 5 | 3 | 8 | 2 |
| services_never_ordered_no_po | fraud_nobank | 5 | 3 | 8 | 5 |
| amount_spike_real_reason | legit | 8 | 4 | 12 | 5 |
| benign_duplicate_resend | legit | 6 | 4 | 10 | 5 |
| credit_memo | legit | 5 | 3 | 8 | 1 |
| international_vendor | legit | 8 | 4 | 12 | 4 |
| legit_bank_change_callback | legit | 8 | 4 | 12 | 7 |
| legit_bank_change_second_contact | legit | 6 | 4 | 10 | 10 |
| partial_split | legit | 6 | 3 | 9 | 0 |
| payment_reminder | legit | 6 | 3 | 9 | 1 |
| po_matched | legit | 9 | 5 | 14 | 1 |
| po_mismatch_legit | legit | 6 | 4 | 10 | 7 |
| portal_notification | legit | 6 | 3 | 9 | 0 |
| recurring_subscription | legit | 6 | 3 | 9 | 0 |
| remit_address_change | legit | 5 | 3 | 8 | 6 |
| routine | legit | 13 | 7 | 20 | 3 |
| vendor_name_change_acquisition | legit | 5 | 3 | 8 | 8 |

### Other dimensions
| sender channel | n | % |
|---|---:|---:|
| vendor | 201 | 67.0% |
| compromised | 38 | 12.7% |
| lookalike | 28 | 9.3% |
| phantom | 16 | 5.3% |
| exec_lookalike | 8 | 2.7% |
| third_party | 8 | 2.7% |
| freemail | 1 | 0.3% |

| thread position | n | % |
|---|---:|---:|
| new | 211 | 70.3% |
| reply_in_thread | 51 | 17.0% |
| reply_all_cc | 20 | 6.7% |
| forward | 18 | 6.0% |

| length bucket | n | % |
|---|---:|---:|
| medium | 122 | 40.7% |
| short | 112 | 37.3% |
| long | 51 | 17.0% |
| oneline | 15 | 5.0% |

| register | n | % |
|---|---:|---:|
| terse | 89 | 29.7% |
| neutral | 68 | 22.7% |
| non_native | 49 | 16.3% |
| chatty | 45 | 15.0% |
| formal | 40 | 13.3% |
| portal_notification | 9 | 3.0% |

| language | n | % |
|---|---:|---:|
| en | 274 | 91.3% |
| es | 12 | 4.0% |
| de | 7 | 2.3% |
| fr | 7 | 2.3% |

| device footer | n | % |
|---|---:|---:|
| none | 120 | 40.0% |
| iphone | 74 | 24.7% |
| desktop_sig | 41 | 13.7% |
| android | 40 | 13.3% |
| outlook_mobile | 25 | 8.3% |

| attachments | n | % |
|---|---:|---:|
| invoice_pdf | 157 | 52.3% |
| none | 86 | 28.7% |
| signed_bank_form | 15 | 5.0% |
| invoice_pdf+spreadsheet | 13 | 4.3% |
| spreadsheet | 7 | 2.3% |
| w9+invoice_pdf | 6 | 2.0% |
| signed_bank_form+invoice_pdf | 5 | 1.7% |
| w9+signed_bank_form | 5 | 1.7% |
| signed_bank_form+w9 | 4 | 1.3% |
| w9 | 2 | 0.7% |

| dnstwist fuzzer (lookalike cases) | n | % |
|---|---:|---:|
| hyphenation | 9 | 32.1% |
| transposition | 8 | 28.6% |
| omission | 4 | 14.3% |
| insertion | 2 | 7.1% |
| replacement | 2 | 7.1% |
| addition | 1 | 3.6% |
| homoglyph | 1 | 3.6% |
| tld-swap | 1 | 3.6% |

| prompt-injection placement | n | % |
|---|---:|---:|
| attachment_text | 3 | 20.0% |
| footer | 3 | 20.0% |
| html_comment | 3 | 20.0% |
| quoted_reply | 3 | 20.0% |
| white_span | 3 | 20.0% |

| tells (ground-truth evidence a careful reviewer could find) | n | % |
|---|---:|---:|
| no_signed_form_or_prior_notice | 53 | 13.4% |
| young_sender_domain | 33 | 8.3% |
| origin_ip_differs_from_usual | 30 | 7.6% |
| lookalike_domain | 28 | 7.1% |
| auth_failures | 23 | 5.8% |
| no_po | 16 | 4.0% |
| unknown_vendor | 16 | 4.0% |
| hidden_prompt_injection | 15 | 3.8% |
| no_po_for_vendor_that_always_uses_po | 15 | 3.8% |
| reply_to_mismatch | 15 | 3.8% |
| amount_just_under_1_5x_typical | 9 | 2.3% |
| mailer_differs_from_history | 9 | 2.3% |
| vague_single_line_item | 9 | 2.3% |
| bank_country_mismatch | 8 | 2.0% |
| bypass_verification | 8 | 2.0% |
| description_off_profile | 8 | 2.0% |
| dormant_vendor_resumes | 8 | 2.0% |
| executive_impersonation | 8 | 2.0% |
| invoice_number_sequence_jump | 8 | 2.0% |
| just_under_approval_threshold | 8 | 2.0% |
| matches_paid_invoice_except_number | 8 | 2.0% |
| no_notice_of_assignment_on_file | 8 | 2.0% |
| no_po_and_no_matching_work | 8 | 2.0% |
| split_bank_details | 8 | 2.0% |
| threshold_splitting_pair | 8 | 2.0% |
| unrecognized_third_party | 8 | 2.0% |
| urgency_pressure | 8 | 2.0% |
| odd_send_hour | 5 | 1.3% |
| form_signatory_not_an_authorized_contact | 4 | 1.0% |
| dkim_missing | 3 | 0.8% |
| freemail_sender_not_on_file | 1 | 0.3% |

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
| hard share >= 35% | pass (42.3%) |
| attribute vectors unique | pass |
| fact check of every email vs its spec | pass (300/300) |
| reserved domains / fake banks only, no real-company names, no label-leak words | pass (code-checked) |
| split by vendor (no vendor in both splits) | pass |
| repetition | max pairwise cosine 0.623, 99th pct 0.176; max 5-gram Jaccard 0.203 (pairs > 0.4: 0); 70 distinct openings, 231 distinct endings (see below) |
| diversity | vocabulary 2992 words; body length median 62 words (min 13, max 163); 6 thread structures; entropy bits: scenario 4.91, register 2.38, length 1.71 |
| shortcut audit | see below: **partial pass, with caveats** |

**Repetition detail.** Most common openings: 'hello' x41, 'afternoon' x29, 'hello ap team' x25, 'greetings' x25, 'dear accounts payable' x23, 'hi' x22. These are normal salutations and track the vendor voice profiles, but the same vendor reuses its own greeting/closing by design (that is the point of a per-vendor baseline). Most common endings (signature blocks/device footers): 'pinnacle logistics group | this message may contain confiden' x5, 'ember haulage corp. | (415) 555-0101' x5, 'jordan | sent from my iphone' x5, 'many thanks, | jordan' x4.

**Shortcut audit** (logistic regression, 5-fold CV **grouped by vendor**; majority baseline label 0.533, lane 0.683):
| feature set | predicts label | predicts expected_lane |
|---|---:|---:|
| artifact_only (length, lines, quoting, attachments, noise, hour, weekday, language, footer, cc, html, urgency) | 0.737 | 0.66 |
| body_text_tfidf_only | 0.91 | 0.76 |
| header_and_fact_features (REAL tells) | 0.87 | 0.83 |
| text+header | 0.91 | 0.833 |

* The first run of this audit found a real artifact: **attachment count alone predicted the label at 0.89** (legit emails averaged 1.06 attachments, fraud 0.13) because most fraud scenarios had been specified with no attachment. Fix: whenever the prose says something is attached/enclosed and the spec has no attachment, an invoice PDF is generated from the email's own facts (59 emails). Artifact-only accuracy dropped to 0.737, below the ~85% bar but still above the 0.533 baseline (residual signal: bank-change vocabulary, PO mentions, quoting and CC habits).
* **Unresolved:** text TF-IDF alone predicts the label at 0.91 and text+header at 0.91. Much of this is legitimate (fraud here is mostly bank-change requests, whose vocabulary differs from invoices, and header tells are real tells), but it means the **easy and medium cases are easy for a linear model (0.971 on label)**. On hard cases the same model gets 0.827, i.e. the hard subset is harder but not hard. Treat the headline numbers on this dataset accordingly and look at hard-case and per-scenario results.

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
4. **Prevalence is not realistic:** 47% fraud, because every one of 31 scenarios needs >= 8 cases. Report precision with this in mind (or reweight).
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
