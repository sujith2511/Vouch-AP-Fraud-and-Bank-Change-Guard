// Vouch console. No framework, no build step. All data is rendered with textContent (never innerHTML):
// vendor emails are untrusted and may contain HTML or instructions.

const STATES = ["NEW", "PROPOSED", "NEEDS_INFO", "APPROVED", "REJECTED", "POSTED"];
const STATE_LABEL = { NEW: "New", PROPOSED: "Proposed", NEEDS_INFO: "Needs info", APPROVED: "Approved", REJECTED: "Rejected", POSTED: "Posted" };
const KEY = "vouch.apiKey";
const S = { me: null, items: [], filter: "ALL", q: "", selected: null };

// ---------------------------------------------------------------- tiny DOM helper
function h(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) e.append(kid instanceof Node ? kid : String(kid));
  return e;
}
const $ = (s) => document.querySelector(s);
const clear = (e) => { while (e.firstChild) e.removeChild(e.firstChild); return e; };
const money = (n, cur = "USD") => (typeof n === "number" ? new Intl.NumberFormat("en-US", { style: "currency", currency: cur || "USD" }).format(n) : "—");
const when = (ts) => (ts ? new Date(ts).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "");
const phone = (d) => (d && d.length === 10 ? `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}` : d || "");

function toast(msg, bad = false) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), bad ? 6000 : 3000);
}

// ---------------------------------------------------------------- API
async function api(path, { method = "GET", body } = {}) {
  const r = await fetch(path, {
    method, headers: { "X-API-Key": sessionStorage.getItem(KEY) || "", ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401) { signOut("Your key was not accepted."); throw new Error("unauthorized"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    const msg = typeof d === "string" ? d : d ? `${d.code || "error"}: ${d.message || ""}`.trim() : `HTTP ${r.status}`;
    const err = new Error(msg); err.status = r.status; err.detail = d; throw err;
  }
  return data;
}
async function act(fn, okMsg) {
  try { const r = await fn(); if (okMsg) toast(okMsg); return r; }
  catch (e) { if (e.message !== "unauthorized") toast(`Denied · ${e.message}`, true); return null; }
}

// ---------------------------------------------------------------- auth
async function signIn(key) {
  sessionStorage.setItem(KEY, key);
  S.me = await api("/me");
  $("#login").hidden = true; $("#app").hidden = false;
  $("#whoami").textContent = `${S.me.user} · ${S.me.role}`;
  await Promise.all([loadQueue(), checkChain()]);
}
function signOut(msg) {
  sessionStorage.removeItem(KEY); S.me = null;
  // the next person starts from a clean queue: no previous tab, search, filter or open item
  Object.assign(S, { items: [], filter: "ALL", q: "", selected: null }); $("#search").value = "";
  clear($("#queue-list")); clear($("#detail")).append(h("div", { class: "empty" }, h("h2", {}, "Select a work item")));
  show("queue");
  $("#app").hidden = true; $("#login").hidden = false; $("#login-error").textContent = msg || ""; $("#key").value = ""; $("#password").value = "";
  Object.assign(D, { scene: null, item: null, reveal: false }); $("#stage").hidden = true; clear($("#out-verify"));
  document.querySelectorAll(".scenario").forEach((b) => b.setAttribute("aria-checked", "false"));
}
async function checkChain() {
  const c = $("#chain");
  try { const r = await api("/audit/verify"); c.textContent = r.ok ? "✓ Audit chain intact" : `✗ Chain broken at #${r.first_bad_id}`; c.className = "chip " + (r.ok ? "chip-ok" : "chip-bad"); }
  catch { c.textContent = "Audit chain ?"; }
}

// ---------------------------------------------------------------- evidence → signals
function toolResults(item) {
  const out = {};
  for (const ev of item.evidence || []) {
    if (Array.isArray(ev.data)) for (const x of ev.data) if (x && x.tool) out[x.tool] = x.result;
    if (ev.by === "policy" && ev.data && ev.data.rules) out.policy_rules = { action: ev.action, rules: ev.data.rules };
  }
  return out;
}
function signals(item) {
  const t = toolResults(item), e = item.email || {}, sig = [];
  const add = (kind, title, detail) => sig.push({ kind, title, detail });
  const auth = e.auth || {};
  const fails = ["spf", "dkim", "dmarc"].filter((k) => auth[k] && auth[k] !== "pass");
  if (Object.keys(auth).length) add(fails.length ? "bad" : "good", fails.length ? "Email authentication failed" : "SPF, DKIM and DMARC pass",
    ["spf", "dkim", "dmarc"].map((k) => `${k.toUpperCase()} ${auth[k] || "—"}`).join(" · "));
  const d = t.check_domain;
  if (d) add(d.exact_match ? "good" : d.lookalike_suspect ? "bad" : "warn", d.exact_match ? "Sender is on the vendor's domain" : d.lookalike_suspect ? "Lookalike sender domain" : "Sender is not on the vendor's domain",
    `${d.sender_domain} vs ${d.vendor_domain}${d.edit_distance ? ` (edit distance ${d.edit_distance})` : ""}`);
  const ps = t.azure_prompt_shields;
  if (ps) add(ps.status !== "ok" ? "warn" : ps.attack_detected ? "bad" : "good", ps.status !== "ok" ? "Azure Prompt Shields: scan unavailable" : ps.attack_detected ? "Azure Prompt Shields: hidden instructions detected" : "Azure Prompt Shields: no injection found",
    ps.status === "ok" ? `${ps.documents || 1} document(s) scanned` : ps.error || ps.status);
  const w = t.verify_vendor_web;
  if (w) {
    const src = w.simulated ? "simulated" : w.source || "live";
    if (w.status !== "ok") add("warn", "Vendor could not be verified online", `web check: ${w.status} (${src})`);
    else if ((w.email_phones_not_listed_online || []).length) add("bad", "Callback number is not one the vendor lists online",
      `email: ${w.email_phones_not_listed_online.map(phone).join(", ")} · official: ${(w.official_phones || []).map(phone).join(", ") || "none"} (${src})`);
    else if ((w.email_phones_unconfirmed || []).length) add("warn", "Phone in the email could not be confirmed", `no official number found online (${src})`);
    else add(w.site_domain_matches_vendor === false ? "bad" : "good", w.site_domain_matches_vendor === false ? "Official website is not on the vendor's domain" : "Vendor verified on the web",
      `${w.official_site || ""} (${src})`);
  }
  const a = t.compare_amounts;
  if (a && a.ratio_to_typical != null) add(a.within_1_5x ? "good" : "warn", a.within_1_5x ? "Amount fits this vendor's history" : "Amount is out of pattern",
    `${a.ratio_to_typical.toFixed(2)}× the typical ${money(a.typical)}`);
  const cc = t.computed_checks;
  if (cc && cc.invoice_number_jump) add("bad", "Invoice number jumps far past the last one", `gap ${cc.invoice_number_gap}, this vendor usually moves ~${cc.usual_gap_between_invoices}`);
  if (cc && cc.split_to_avoid_approval) add("bad", "Possible split to stay under the approval limit", "a related invoice from the same vendor is in the queue");
  if (item.is_bank_change) add("warn", "Bank-change request", "always needs a human: the rulebook never auto-approves it");
  const pr = t.policy_rules;
  if (pr) {
    const failed = Object.entries(pr.rules).filter(([, v]) => !v).map(([k]) => k.replaceAll("_", " "));
    add(pr.action === "approve" ? "good" : "bad", pr.action === "approve" ? "Policy lane auto-cleared it (all low-risk rules passed)" : "Policy lane rejected it", failed.length ? `failed: ${failed.join(", ")}` : "every rule passed");
  }
  return sig;
}
const verdictChip = (v) => (v ? h("span", { class: "chip " + ({ fraud: "chip-bad", legit: "chip-ok", uncertain: "chip-warn" }[v.verdict] || "") }, v.verdict) : null);
const stateChip = (s) => h("span", { class: "chip " + ({ REJECTED: "chip-bad", POSTED: "chip-ok", APPROVED: "chip-ok", NEEDS_INFO: "chip-warn", PROPOSED: "chip-info" }[s] || "") }, STATE_LABEL[s] || s);

// ---------------------------------------------------------------- queue
async function loadQueue(keep = true) {
  S.items = await api("/items?limit=500");
  S.items.sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
  renderFilters(); renderQueue();
  if (keep && S.selected) { const it = S.items.find((i) => i.id === S.selected); if (it) renderDetail(it); }
}
function renderFilters() {
  const counts = Object.fromEntries(STATES.map((s) => [s, S.items.filter((i) => i.state === s).length]));
  const f = clear($("#state-filters"));
  for (const s of ["ALL", ...STATES]) {
    const n = s === "ALL" ? S.items.length : counts[s];
    f.append(h("button", { class: "filter" + (S.filter === s ? " on" : ""), onclick: () => { S.filter = s; renderFilters(); renderQueue(); } },
      `${s === "ALL" ? "All" : STATE_LABEL[s]} ${n}`));
  }
}
function renderQueue() {
  const q = S.q.toLowerCase();
  const list = S.items.filter((i) => (S.filter === "ALL" || i.state === S.filter) &&
    (!q || [i.id, i.vendor?.name, i.email?.subject, i.claim?.invoice_number, i.email?.from].join(" ").toLowerCase().includes(q)));
  const el = clear($("#queue-list"));
  for (const i of list.slice(0, 400)) {
    el.append(h("div", { class: "qi" + (S.selected === i.id ? " sel" : ""), role: "listitem", tabindex: "0",
      onclick: () => select(i.id), onkeydown: (ev) => ev.key === "Enter" && select(i.id) },
      h("div", { class: "qi-top" }, h("span", { class: "qi-vendor" }, i.vendor?.name || i.vendor_id), h("span", { class: "qi-amt" }, money(i.claim?.amount, i.claim?.currency))),
      h("div", { class: "qi-subj" }, i.email?.subject || "(no subject)"),
      h("div", { class: "qi-tags" }, stateChip(i.state), verdictChip(i.verdict), i.is_bank_change ? h("span", { class: "chip chip-warn" }, "bank change") : null,
        h("span", { class: "chip mono" }, i.id))));
  }
  $("#queue-foot").textContent = `${list.length} of ${S.items.length} items`;
}
async function select(id) {
  S.selected = id; renderQueue();
  const it = await act(() => api(`/items/${encodeURIComponent(id)}`));
  if (it) renderDetail(it);
}

// ---------------------------------------------------------------- detail
async function renderDetail(it) {
  const d = clear($("#detail")), e = it.email || {}, c = it.claim || {}, v = it.vendor || {};
  d.append(h("div", { class: "d-head" },
    h("div", {}, h("p", { class: "d-title" }, v.name || it.vendor_id),
      h("div", { class: "d-sub" }, `${it.id} · ${c.invoice_number || "no invoice number"}${c.po ? ` · PO ${c.po}` : ""}`),
      h("div", { class: "row mt6" }, stateChip(it.state), it.is_bank_change ? h("span", { class: "chip chip-warn" }, "bank change") : null)),
    h("div", {}, h("div", { class: "d-amt" }, money(c.amount, c.currency)), h("div", { class: "d-sub right" }, `typical ${money(v.typical_amount, c.currency)}`))));

  // verdict
  const vv = it.verdict;
  const vc = h("section", { class: "card verdict" + (vv ? ` v-${vv.verdict}` : "") }, h("h4", {}, "Agent proposal"));
  if (vv) {
    vc.append(h("div", { class: "v-row" }, h("span", { class: "v-label" }, vv.verdict), vv.confidence != null ? h("span", { class: "chip" }, `confidence ${Math.round(vv.confidence * 100)}%`) : null,
      h("span", { class: "muted" }, "The agent only proposes. A human decides; only the gateway can pay.")));
    vc.append(h("ul", { class: "reasons" }, (vv.reasons || []).map((r) => h("li", { class: r.startsWith("guard:") ? "guard" : "" }, r))));
  } else vc.append(h("p", { class: "muted" }, "Not investigated yet."));
  if (it.question) vc.append(h("div", { class: "question" }, h("b", {}, "Agent asks: "), it.question, it.answer ? h("div", {}, h("b", {}, `Answer (${it.answered_by}): `), it.answer) : null));
  d.append(vc);

  // actions
  d.append(actionsCard(it));

  // signals + bank
  const sig = signals(it);
  d.append(h("div", { class: "grid2" },
    h("section", { class: "card" }, h("h4", {}, "Evidence"), sig.length ? h("div", { class: "signals" }, sig.map((s) =>
      h("div", { class: `signal ${s.kind}` }, h("span", { class: "dot" }), h("div", {}, h("b", {}, s.title), h("span", { class: "muted" }, s.detail))))) : h("p", { class: "muted" }, "No evidence yet.")),
    h("section", { class: "card" }, h("h4", {}, "Bank details"),
      h("div", { class: "bank-compare" },
        h("div", { class: "bank" }, h("b", {}, "On file"), bankLines(v.bank)),
        h("div", { class: "bank" + (it.is_bank_change ? " changed" : "") }, h("b", {}, it.is_bank_change ? "Requested (new)" : "Requested"), c.claimed_bank ? bankLines(c.claimed_bank) : h("div", { class: "muted" }, "no change requested"))),
      h("div", { class: "row mt10" }, h("button", { class: "btn btn-sm", onclick: () => vendorWhy(it.vendor_id, d) }, "Why was this vendor's bank changed?")))));

  // email (untrusted)
  const att = (e.attachments || []).map((a) => h("details", {}, h("summary", {}, `📎 ${a.filename || "attachment"} (${a.type || "file"})`), h("pre", { class: "email-body" }, a.extracted_text || "")));
  d.append(h("section", { class: "card untrusted" }, h("span", { class: "untrusted-label" }, "Untrusted vendor email · shown as plain text"),
    h("dl", { class: "kv" }, h("dt", {}, "From"), h("dd", { class: "mono" }, e.from || ""), h("dt", {}, "Reply-to"), h("dd", { class: "mono" }, e.reply_to || ""),
      e.headers?.mailer ? [h("dt", {}, "Mailer"), h("dd", {}, `${e.headers.mailer}${e.headers.origin_ip ? ` · ${e.headers.origin_ip}` : ""}`)] : null,
      h("dt", {}, "Subject"), h("dd", {}, e.subject || "")),
    h("pre", { class: "email-body" }, e.body || ""), att));

  // timeline
  const tl = h("section", { class: "card" }, h("h4", {}, "Why? · audit trail"), h("p", { class: "muted" }, "Loading…"));
  d.append(tl);
  const rows = await act(() => api(`/items/${encodeURIComponent(it.id)}/audit`));
  if (rows) {
    clear(tl).append(h("h4", {}, "Why? · audit trail (hash-chained, append-only)"), h("ul", { class: "timeline" }, rows.map((r) =>
      h("li", { class: r.outcome === "denied" ? "denied" : "" }, h("span", { class: "tl-when" }, when(r.ts)),
        h("div", { class: "tl-what" }, h("b", {}, `${r.actor}${r.actor_id ? ` (${r.actor_id})` : ""}`), `${r.action}`,
          r.from_state || r.to_state ? h("span", { class: "muted" }, `  ${r.from_state || "∅"} → ${r.to_state || "—"}`) : null,
          r.outcome === "denied" ? h("span", { class: "chip chip-bad ml8" }, `DENIED ${r.deny_code || ""}`) : null,
          r.reason ? h("div", { class: "muted" }, r.reason) : null)))));
  }
}
const bankLines = (b) => (b ? [h("div", {}, b.bank_name || "—"), h("div", { class: "mono" }, `routing ${b.routing || b.routing_or_iban || "—"}`), h("div", { class: "mono" }, `account ${b.account || "—"}`)] : h("div", { class: "muted" }, "—"));

function actionsCard(it) {
  const role = S.me?.role, card = h("section", { class: "card" }, h("h4", {}, "Decision"));
  const reason = h("textarea", { placeholder: "Written reason (required for approve / reject, min 5 characters)" });
  const refresh = async () => { await loadQueue(); await checkChain(); };
  const run = (label, fn, cls = "btn") => h("button", { class: cls, onclick: async (ev) => { ev.target.disabled = true; const r = await act(fn, label); ev.target.disabled = false; if (r) refresh(); } }, label);
  const note = (t) => h("p", { class: "muted" }, t);
  if (it.state === "NEW") {
    card.append(note("Not investigated yet. The agent reads the email, checks the vendor record, domain, amount, web and Prompt Shields, then proposes."),
      h("div", { class: "row" }, run("Run the agent", () => api(`/items/${it.id}/investigate`, { method: "POST" }), "btn btn-primary")));
  } else if (it.state === "PROPOSED") {
    card.append(note(it.is_bank_change ? "Bank change: approving it needs a different accountant than the one who answered the agent's question." : "Approve to queue it for payment, or reject it."),
      reason, h("div", { class: "row" },
        run("Approve", () => api(`/items/${it.id}/approve`, { method: "POST", body: { reason: reason.value } }), "btn btn-ok"),
        run("Reject", () => api(`/items/${it.id}/reject`, { method: "POST", body: { reason: reason.value } }), "btn btn-danger")));
  } else if (it.state === "NEEDS_INFO") {
    const ans = h("textarea", { placeholder: "What did you find? e.g. 'Called the number on file; vendor confirmed the change.'" });
    card.append(note("The agent asked a human to verify something (see above)."), ans,
      h("div", { class: "row" }, run("Send answer", () => api(`/items/${it.id}/answer`, { method: "POST", body: { answer: ans.value } }), "btn btn-primary")));
  } else if (it.state === "APPROVED") {
    card.append(note(`Approved by ${it.approved_by}. Only the gateway can release payment (and change bank details); it refuses anything not APPROVED.`),
      h("div", { class: "row" }, run("Release via gateway", () => api(`/items/${it.id}/post`, { method: "POST", body: { reason: "release approved item" } }), "btn btn-primary")));
  } else {
    card.append(note(it.state === "POSTED" ? "Paid by the gateway. Nothing more can happen to this item." : "Rejected. Nothing more can happen to this item."));
  }
  card.append(h("p", { class: "fine" }, `Signed in as ${S.me?.user} (${role}). The server decides what this role may do; denied attempts are logged.`));
  return card;
}

async function vendorWhy(vendorId, container) {
  const r = await act(() => api(`/vendors/${encodeURIComponent(vendorId)}/why`));
  if (!r) return;
  const box = h("section", { class: "card" }, h("h4", {}, "Why was this vendor's bank changed?"), h("p", {}, r.summary));
  for (const ch of r.changes || []) box.append(h("p", { class: "muted" }, `${when(ch.changed_at)} · item ${ch.item_id} · approved by ${ch.approved_by?.actor_id || ch.approved_by?.actor || "?"}: ${ch.approved_by?.reason || ""}`));
  container.insertBefore(box, container.children[2] || null);
}

// ---------------------------------------------------------------- policies
async function loadPolicies() {
  const [ps, cs] = await Promise.all([api("/policies"), api("/policies/corrections")]);
  const corr = clear($("#corrections"));
  corr.append(h("h4", {}, `Human corrections (${cs.length})`), cs.length ? h("ul", { class: "reasons" }, cs.map((c) =>
    h("li", {}, `${c.item_id}: agent said ${c.agent_verdict}, ${c.human_id} chose to ${c.human_action} — "${c.human_reason}" → would make the agent ${c.direction}`)))
    : h("p", { class: "muted" }, "None yet. Overrule an agent verdict in the work queue (approve a 'fraud' or reject a 'legit') to create one."));
  const list = clear($("#policy-list"));
  if (!ps.length) list.append(h("p", { class: "muted" }, "No policies yet."));
  for (const p of ps.slice().reverse()) {
    const reason = h("input", { placeholder: "Reason (required)" });
    const decide = (ok) => async () => { const r = await act(() => api(`/policies/${p.id}/${ok ? "approve" : "reject"}`, { method: "POST", body: { reason: reason.value } }), ok ? "Policy approved" : "Policy rejected"); if (r) loadPolicies(); };
    list.append(h("article", { class: "card policy" },
      h("div", { class: "row" }, h("span", { class: "chip " + ({ APPROVED: "chip-ok", REJECTED: "chip-bad", PROPOSED: "chip-info" }[p.state]) }, p.state),
        h("span", { class: "chip " + (p.direction === "looser" ? "chip-warn" : "chip-info") }, p.direction === "looser" ? "makes the agent more lenient" : "makes the agent stricter"),
        h("span", { class: "chip mono" }, p.id), p.source_item ? h("span", { class: "muted" }, `from ${p.source_item}`) : null),
      h("div", { class: "rule" }, p.rule), p.rationale ? h("div", { class: "muted" }, p.rationale) : null,
      p.state === "PROPOSED" ? h("div", { class: "row" }, reason, h("button", { class: "btn btn-ok", onclick: decide(true) }, "Approve"), h("button", { class: "btn btn-danger", onclick: decide(false) }, "Reject"))
        : h("div", { class: "fine" }, `${p.state.toLowerCase()} by ${p.decided_by}: ${p.decision_reason || ""}`)));
  }
}

// ---------------------------------------------------------------- demo: one attack, walked through the real pipeline
const HIDDEN = /<!--[\s\S]*?-->/g;
const D = { scene: null, item: null, running: false, reveal: false };

function webBlock(w) {
  if (!w) return null;
  const src = w.source === "live" ? "live Bright Data lookup" : w.placeholder ? "recorded placeholder (not a real response)" : w.source === "recorded" ? `recorded Bright Data response${w.recorded_at ? ` (${when(w.recorded_at)})` : ""}` : w.source || "";
  return h("dl", { class: "kv" }, h("dt", {}, "Web check"), h("dd", {}, `${w.status} · ${src}`),
    h("dt", {}, "Official site"), h("dd", {}, w.official_site || "—"),
    h("dt", {}, "Phones online"), h("dd", { class: "mono" }, (w.official_phones || []).map(phone).join(", ") || "none found"),
    w.phone_on_file_listed_online != null ? [h("dt", {}, "SEC-registered phone listed online"), h("dd", {}, w.phone_on_file_listed_online ? "yes" : "no")] : null);
}

// The email as a person sees it (hidden HTML comments removed), or as the model receives it (comments shown and marked).
function renderMail(it) {
  const m = clear($("#mail")), e = it.email || {}, body = e.body || "";
  const hasHidden = HIDDEN.test(body); HIDDEN.lastIndex = 0;
  $("#reveal").hidden = !hasHidden; $("#reveal").setAttribute("aria-pressed", String(D.reveal));
  $("#reveal").textContent = D.reveal ? "Show what a person sees" : "Show what the AI receives";
  const pre = h("pre", { class: "email-body mail-body" });
  if (D.reveal) {
    let last = 0;
    for (const mt of body.matchAll(HIDDEN)) { pre.append(body.slice(last, mt.index), h("mark", { class: "hidden-text" }, mt[0])); last = mt.index + mt[0].length; }
    pre.append(body.slice(last));
  } else pre.append(body.replace(HIDDEN, "").trimEnd());
  const auth = e.auth || {};
  m.append(h("div", { class: "mail-head" },
    h("div", { class: "mail-subj" }, e.subject || ""),
    h("div", { class: "mono" }, e.from || ""),
    h("div", { class: "row wrap" }, ["spf", "dkim", "dmarc"].map((k) => h("span", { class: "chip " + (auth[k] === "pass" ? "chip-ok" : "chip-bad") }, `${k.toUpperCase()} ${auth[k] || "—"}`)),
      h("span", { class: "chip" }, money(it.claim?.amount, it.claim?.currency)))),
    pre, D.reveal && hasHidden ? h("p", { class: "fine" }, "Highlighted: an HTML comment. Invisible in a mail client, but it is in the text an AI reads.") : null);
}

// Pipeline steps, each computed from the item's recorded evidence (nothing here is scripted).
function steps(it) {
  const t = toolResults(it), e = it.email || {}, v = it.verdict || {}, out = [];
  const step = (title, tag, kind, detail) => out.push({ title, tag, kind, detail });
  step("Email becomes a work item", "state machine", "good", `${it.id} · NEW · written to the audit log`);
  const ps = t.azure_prompt_shields;
  step("Azure Prompt Shields scan", "Microsoft", !ps || ps.status !== "ok" ? "skip" : ps.attack_detected ? "bad" : "good",
    !ps ? "not run" : ps.status !== "ok" ? `scan ${ps.status}` : ps.attack_detected ? "hidden instructions detected in the email" : "no injection found");
  const auth = e.auth || {}, fails = ["spf", "dkim", "dmarc"].filter((k) => auth[k] && auth[k] !== "pass");
  step("Email authentication", "SPF · DKIM · DMARC", fails.length ? "bad" : "good", fails.length ? `failed: ${fails.join(", ").toUpperCase()}` : "all pass (so this alone proves nothing)");
  const d = t.check_domain;
  step("Sender vs vendor of record", "domain check", !d ? "skip" : d.exact_match ? "good" : "bad",
    !d ? "not checked" : d.exact_match ? `${d.sender_domain} is the vendor's domain` : `${d.sender_domain} ≠ ${d.vendor_domain}${d.lookalike_suspect ? ` · lookalike, ${d.edit_distance} letter off` : ""}`);
  const w = t.verify_vendor_web;
  const notListed = (w?.email_phones_not_listed_online || []);
  step("Live web check", "Bright Data", !w || w.status === "not_applicable" ? "skip" : w.status !== "ok" ? "warn" : notListed.length ? "bad" : "good",
    !w || w.status === "not_applicable" ? "fictional vendor: no lookup" : w.status !== "ok" ? `could not verify (${w.status})`
      : notListed.length ? `callback ${notListed.map(phone).join(", ")} is not a number the company lists online (${w.source || "live"})` : `official site ${w.official_site || "found"} (${w.source || "live"})`);
  const tools = Object.keys(t).filter((k) => !["policy_rules", "azure_prompt_shields", "verify_vendor_web", "computed_checks"].includes(k));
  step("Claude Haiku 4.5 investigates", "Anthropic", v.verdict === "fraud" ? "bad" : v.verdict === "legit" ? "good" : "warn",
    v.verdict ? `${tools.length} read-only tool calls → proposes "${v.verdict}"${v.confidence != null ? ` at ${Math.round(v.confidence * 100)}%` : ""}` : "no proposal");
  const guard = (v.reasons || []).filter((r) => r.startsWith("guard:"));
  step("Code guard", "can only make it stricter", guard.length ? "bad" : "good", guard.length ? `${guard.length} rule(s) overrode the model` : "agreed with the model; nothing to override");
  const pr = t.policy_rules;
  const failed = pr ? Object.entries(pr.rules).filter(([, x]) => !x).length : 0;
  step("Policy lane", "rules in code", it.state === "REJECTED" ? "bad" : it.state === "APPROVED" ? "good" : "warn",
    it.state === "REJECTED" ? `rejected · ${failed} low-risk rule(s) failed` : it.state === "APPROVED" ? "auto-cleared: every low-risk rule passed" : "sent to a human");
  step("Payment gateway", "the only thing that pays", it.state === "POSTED" ? "warn" : "good", it.state === "POSTED" ? "paid" : "$0 moved · it refuses anything not APPROVED by a human");
  return out;
}

function pendingSteps() {
  const names = [["Email becomes a work item", "state machine"], ["Azure Prompt Shields scan", "Microsoft"], ["Email authentication", "SPF · DKIM · DMARC"],
    ["Sender vs vendor of record", "domain check"], ["Live web check", "Bright Data"], ["Claude Haiku 4.5 investigates", "Anthropic"],
    ["Code guard", "can only make it stricter"], ["Policy lane", "rules in code"], ["Payment gateway", "the only thing that pays"]];
  const ol = clear($("#steps"));
  names.forEach(([title, tag], i) => ol.append(h("li", { class: "step " + (i === 0 ? "running" : "queued") }, h("span", { class: "step-dot" }),
    h("div", {}, h("div", { class: "step-title" }, title, h("span", { class: "step-tag" }, tag)), h("div", { class: "step-detail muted" }, i === 0 ? "running…" : "")))));
}

async function revealSteps(list) {
  const ol = clear($("#steps"));
  for (const s of list) {
    ol.append(h("li", { class: `step ${s.kind} pop` }, h("span", { class: "step-dot" }),
      h("div", {}, h("div", { class: "step-title" }, s.title, h("span", { class: "step-tag" }, s.tag)), h("div", { class: "step-detail" }, s.detail))));
    await new Promise((r) => setTimeout(r, 260));
  }
}

const STAMP = { REJECTED: ["Blocked", "bad"], PROPOSED: ["Held for a human", "warn"], NEEDS_INFO: ["Held: callback required", "warn"], APPROVED: ["Auto-cleared", "ok"], POSTED: ["Paid", "warn"] };

async function renderOutcome(it) {
  const o = clear($("#outcome")), [label, kind] = STAMP[it.state] || [it.state, "warn"], v = it.verdict || {};
  o.append(h("div", { class: `stamp stamp-${kind}` }, label),
    h("div", { class: "money-line" }, h("s", {}, money(it.claim?.amount, it.claim?.currency)), h("b", {}, " → $0.00 moved")),
    h("ul", { class: "reasons" }, (v.reasons || []).slice(0, 5).map((r) => h("li", { class: r.startsWith("guard:") ? "guard" : "" }, r.replace(/^,\s*/, "")))));
  if (it.question) o.append(h("div", { class: "question" }, h("b", {}, "Agent asks a human: "), it.question));
  const res = h("div", { class: "attempts" });
  const attempt = (label, fn) => h("button", { class: "btn btn-danger btn-sm", type: "button", onclick: async (ev) => {
    ev.target.disabled = true;
    try { await fn(); res.append(h("div", { class: "attempt ok" }, `${label}: allowed`)); }
    catch (e) { if (e.message !== "unauthorized") res.append(h("div", { class: "attempt" }, h("b", {}, "✗ Denied "), `${label} · ${e.message}`)); }
    ev.target.disabled = false; await renderTrail(it.id); checkChain();
  } }, label);
  o.append(h("h4", { class: "mt14" }, "Now try to break it"),
    h("p", { class: "muted" }, `You are signed in as ${S.me?.user} (${S.me?.role}). These are real requests to the server.`),
    h("div", { class: "row wrap" },
      it.state === "REJECTED" ? attempt("Approve it anyway", () => api(`/items/${it.id}/approve`, { method: "POST", body: { reason: "demo: override the rejection" } })) : null,
      attempt("Force the payment", () => api(`/items/${it.id}/post`, { method: "POST", body: { reason: "demo: pay it now" } }))),
    res, h("div", { id: "trail" }),
    h("button", { class: "btn btn-sm mt10", type: "button", onclick: async () => { show("queue"); await loadQueue(); select(it.id); } }, `Open ${it.id} in the work queue`));
  await renderTrail(it.id);
}

async function renderTrail(id) {
  const box = $("#trail"); if (!box) return;
  const rows = await act(() => api(`/items/${encodeURIComponent(id)}/audit`)); if (!rows) return;
  const chain = await act(() => api("/audit/verify"));
  clear(box).append(h("h4", { class: "mt14" }, "Audit trail ", chain ? h("span", { class: "chip " + (chain.ok ? "chip-ok" : "chip-bad") }, chain.ok ? "✓ hash chain verified" : "✗ chain broken") : null),
    h("ul", { class: "trail" }, rows.map((r) => h("li", { class: r.outcome === "denied" ? "denied" : "" },
      h("span", { class: "mono hash" }, (r.row_hash || "").slice(0, 8)),
      h("span", {}, h("b", {}, r.actor_id || r.actor), ` ${r.action}`, r.outcome === "denied" ? h("span", { class: "chip chip-bad ml8" }, `DENIED ${r.deny_code || ""}`) : r.to_state ? h("span", { class: "muted" }, ` → ${r.to_state}`) : null)))));
}

async function runScene(scene) {
  if (D.running) return;
  D.running = true; D.scene = scene; D.reveal = false;
  document.querySelectorAll(".scenario").forEach((b) => { b.setAttribute("aria-checked", String(b.dataset.scene === scene)); b.disabled = true; });
  $("#stage").hidden = false; pendingSteps(); clear($("#mail")).append(h("p", { class: "muted" }, "Sending the email…")); $("#reveal").hidden = true;
  clear($("#outcome")).append(h("p", { class: "muted" }, "Waiting for the pipeline…"));
  const t0 = performance.now(), tick = setInterval(() => ($("#timer").textContent = `${((performance.now() - t0) / 1000).toFixed(1)} s`), 100);
  $("#stage").scrollIntoView({ behavior: "smooth", block: "start" });
  const r = await act(() => api(scene === "inject" ? "/demo/inject" : "/demo/real-claim", { method: "POST", body: scene === "inject" ? undefined : {} }));
  clearInterval(tick);
  if (r) {
    $("#timer").textContent = `done in ${((performance.now() - t0) / 1000).toFixed(1)} s`;
    D.item = r.item; renderMail(r.item); await revealSteps(steps(r.item)); await renderOutcome(r.item); checkChain();
  } else { clear($("#steps")); $("#timer").textContent = "failed"; }
  document.querySelectorAll(".scenario").forEach((b) => (b.disabled = false));
  D.running = false;
}

// ---------------------------------------------------------------- wiring
function show(view) {
  for (const t of document.querySelectorAll(".tab")) t.classList.toggle("active", t.dataset.view === view);
  for (const v of ["queue", "policies", "demo"]) $(`#view-${v}`).hidden = v !== view;
  if (view === "policies") act(loadPolicies);
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => show(t.dataset.view)));
document.querySelectorAll(".scenario").forEach((b) => b.addEventListener("click", () => runScene(b.dataset.scene)));
$("#reveal").addEventListener("click", () => { D.reveal = !D.reveal; if (D.item) renderMail(D.item); });
$("#verify").addEventListener("click", async (ev) => {
  ev.target.disabled = true; const out = clear($("#out-verify")).appendChild(h("p", { class: "muted" }, "Searching the live web…")).parentNode;
  const r = await act(() => api(`/demo/verify/${$("#demo-vendor").value}`)); clear(out); if (r) out.append(webBlock(r)); ev.target.disabled = false;
});
$("#search").addEventListener("input", (e) => { S.q = e.target.value; renderQueue(); });
$("#logout").addEventListener("click", () => signOut());
$("#draft-policies").addEventListener("click", async () => { const r = await act(() => api("/policies/draft", { method: "POST" })); if (r) { toast(`${r.length} polic${r.length === 1 ? "y" : "ies"} drafted`); loadPolicies(); } });
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault(); $("#login-error").textContent = "";
  const r = await fetch("/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: $("#username").value, password: $("#password").value }) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { $("#login-error").textContent = typeof data.detail === "string" ? data.detail : `Sign-in failed (HTTP ${r.status})`; return; }
  try { await signIn(data.api_key); } catch (err) { if (err.message !== "unauthorized") $("#login-error").textContent = err.message; }
});
$("#key-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await signIn($("#key").value.trim()); } catch (err) { if (err.message !== "unauthorized") $("#key-error").textContent = err.message; }
});
$("#login-mode").addEventListener("click", () => {
  const useKey = $("#key-form").hidden; $("#key-form").hidden = !useKey; $("#login-form").hidden = useKey;
  $("#login-mode").textContent = useKey ? "Use username and password instead" : "Use an API key instead (controller, other roles)";
});

(async () => {
  if (sessionStorage.getItem(KEY)) { try { await signIn(sessionStorage.getItem(KEY)); return; } catch { /* fall through to login */ } }
  signOut();
})();
