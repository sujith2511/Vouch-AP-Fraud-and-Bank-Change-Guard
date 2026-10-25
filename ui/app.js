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
  $("#app").hidden = true; $("#login").hidden = false; $("#login-error").textContent = msg || ""; $("#key").value = "";
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

// ---------------------------------------------------------------- demo
function webBlock(w) {
  if (!w) return null;
  const src = w.source === "live" ? "live Bright Data lookup" : w.placeholder ? "recorded placeholder (not a real response)" : w.source === "recorded" ? `recorded Bright Data response${w.recorded_at ? ` (${when(w.recorded_at)})` : ""}` : w.source || "";
  return h("dl", { class: "kv" }, h("dt", {}, "Web check"), h("dd", {}, `${w.status} · ${src}`),
    h("dt", {}, "Official site"), h("dd", {}, w.official_site || "—"),
    h("dt", {}, "Phones online"), h("dd", { class: "mono" }, (w.official_phones || []).map(phone).join(", ") || "none found"),
    w.phone_on_file_listed_online != null ? [h("dt", {}, "Registered phone listed"), h("dd", {}, w.phone_on_file_listed_online ? "yes" : "no")] : null);
}
async function runDemo(kind) {
  const out = clear($(`#out-${kind}`)); out.append(h("p", { class: "muted" }, "Running…"));
  let r;
  if (kind === "inject") r = await act(() => api("/demo/inject", { method: "POST" }), "Attack email processed");
  if (kind === "real-claim") r = await act(() => api("/demo/real-claim", { method: "POST", body: {} }), "Scene processed");
  if (kind === "verify") r = await act(() => api(`/demo/verify/${$("#demo-vendor").value}`));
  clear(out); if (!r) return;
  if (kind === "verify") { out.append(webBlock(r)); return; }
  const it = r.item;
  out.append(h("div", { class: "row" }, h("b", {}, `Lane: ${r.lane}`), stateChip(it.state), verdictChip(it.verdict)),
    h("ul", { class: "reasons" }, (it.verdict?.reasons || []).slice(0, 5).map((x) => h("li", { class: x.startsWith("guard:") ? "guard" : "" }, x))));
  if (r.phone_check) out.append(h("p", {}, `Number in the email: ${r.phone_check.phone_in_email} · listed by the company online: ${(r.phone_check.not_listed_online || []).length ? "NO" : "yes"}`));
  if (r.web_verification) out.append(webBlock(r.web_verification));
  out.append(h("button", { class: "btn btn-sm", onclick: async () => { show("queue"); await loadQueue(); select(it.id); } }, `Open ${it.id} in the work queue`));
}

// ---------------------------------------------------------------- wiring
function show(view) {
  for (const t of document.querySelectorAll(".tab")) t.classList.toggle("active", t.dataset.view === view);
  for (const v of ["queue", "policies", "demo"]) $(`#view-${v}`).hidden = v !== view;
  if (view === "policies") act(loadPolicies);
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => show(t.dataset.view)));
document.querySelectorAll("[data-demo]").forEach((b) => b.addEventListener("click", async () => { b.disabled = true; await runDemo(b.dataset.demo); b.disabled = false; }));
$("#search").addEventListener("input", (e) => { S.q = e.target.value; renderQueue(); });
$("#logout").addEventListener("click", () => signOut());
$("#draft-policies").addEventListener("click", async () => { const r = await act(() => api("/policies/draft", { method: "POST" })); if (r) { toast(`${r.length} polic${r.length === 1 ? "y" : "ies"} drafted`); loadPolicies(); } });
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await signIn($("#key").value.trim()); } catch (err) { if (err.message !== "unauthorized") $("#login-error").textContent = err.message; }
});

(async () => {
  if (sessionStorage.getItem(KEY)) { try { await signIn(sessionStorage.getItem(KEY)); return; } catch { /* fall through to login */ } }
  signOut();
})();
