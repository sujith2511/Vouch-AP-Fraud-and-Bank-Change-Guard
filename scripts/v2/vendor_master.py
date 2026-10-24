"""Stage 1: data/v2/vendors.v2.json + data/v2/payments.v2.jsonl + data/v2/history_specs.json.

REAL: payee spellings, SF voucher ids, PO numbers, fiscal years, amounts (USD), SF department.
DERIVED (from real fields by code): industry, size band, typical amount/spread, cadence, active years, PO policy.
SIMULATED (marked): invoice/due/paid dates, invoice numbers, terms, methods, contacts' behaviour, bank-change history.
FABRICATED (must be fake): names, domains, phones, contacts, banks, tax ids.
ERP data (data/raw/erp_fraud) is not available here, so date timing uses documented defaults, not ERP-fitted distributions.
"""
import calendar, sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import *

INDUSTRY = {"Ridge": "general contracting", "Works": "manufacturing", "Supply": "industrial supply", "Dynamics": "engineering services", "Partners": "professional services",
            "Haulage": "logistics & freight", "Labs": "laboratory services", "Industrial": "industrial services", "Analytics": "data & analytics", "Logistics": "logistics & freight",
            "Fabrication": "metal fabrication", "Systems": "IT systems", "Textiles": "textiles & uniforms", "Controls": "building controls", "Instruments": "instrumentation",
            "Mechanical": "mechanical contracting", "Electric": "electrical contracting", "Hydraulics": "hydraulics & pumps", "Dataworks": "software & data", "Consulting": "consulting",
            "Packaging": "packaging supply", "Engineering": "engineering services", "Metals": "metals supply", "Networks": "telecom & networks", "Freightways": "logistics & freight",
            "Fabricators": "metal fabrication", "Robotics": "robotics & automation", "Environmental": "environmental services"}
LINE_ITEMS = {  # plausible invoice line descriptions by industry (used by the case-spec stage)
    "general contracting": ["Site preparation labor", "Concrete work, phase {n}", "Equipment rental, week of {d}", "Materials, lot {n}"],
    "manufacturing": ["Machined part set {n}", "Tooling charge", "Production run {n}", "Packaging and crating"],
    "industrial supply": ["Fasteners assortment", "Safety supplies, order {n}", "Gaskets and seals", "Freight and handling"],
    "engineering services": ["Engineering review hours", "CAD drafting", "Site survey", "Technical memo {n}"],
    "professional services": ["Advisory hours, {d}", "Project management", "Document preparation", "Expenses (travel)"],
    "logistics & freight": ["Freight, route {n}", "Fuel surcharge", "Pallet handling", "Detention charge"],
    "laboratory services": ["Sample analysis batch {n}", "Courier pickup", "Report preparation", "Rush surcharge"],
    "industrial services": ["On-site service call", "Parts and labor", "Inspection visit", "Mobilization"],
    "data & analytics": ["Data platform subscription", "Analyst hours", "Custom report {n}", "Onboarding"],
    "metal fabrication": ["Fabricated assembly {n}", "Welding labor", "Powder coating", "Material surcharge"],
    "IT systems": ["Managed services, {d}", "Hardware: network switch", "Support hours", "License renewal"],
    "textiles & uniforms": ["Uniform order {n}", "Embroidery setup", "Alterations", "Shipping"],
    "building controls": ["Controller replacement", "Commissioning labor", "Sensor kit {n}", "Service agreement"],
    "instrumentation": ["Calibration service", "Sensor module {n}", "Field service visit", "Parts"],
    "mechanical contracting": ["HVAC maintenance visit", "Pump replacement", "Labor, {d}", "Refrigerant"],
    "electrical contracting": ["Electrical repair labor", "Panel upgrade", "Fixtures and materials", "Permit fees"],
    "hydraulics & pumps": ["Pump rebuild kit {n}", "Hose assemblies", "Field repair", "Parts freight"],
    "software & data": ["Software subscription, {d}", "Implementation hours", "Support tier upgrade", "Integration work"],
    "consulting": ["Consulting hours, {d}", "Workshop facilitation", "Deliverable {n}", "Expenses"],
    "packaging supply": ["Corrugated cartons lot {n}", "Stretch wrap", "Labels", "Freight"],
    "metals supply": ["Steel plate lot {n}", "Cutting charge", "Aluminum stock", "Delivery"],
    "telecom & networks": ["Circuit charges, {d}", "Equipment lease", "Installation", "Support"],
    "robotics & automation": ["Robot cell maintenance", "Spare parts kit {n}", "Programming hours", "Training session"],
    "environmental services": ["Environmental sampling {n}", "Disposal fee", "Consultant hours", "Mobilization"]}
US_BANKS = ["Harbor Federal Savings", "Pacific Ridge Bank", "Cedar Valley Credit Union", "Meridian Trust", "Lakeshore Commerce Bank", "Summit Community Bank", "Granite State Savings",
            "Bayview Mutual", "Oakline Bank & Trust", "First Prairie Bank", "Evergreen Credit Union", "Tidewater National", "Redwood Mutual Bank", "Copperline Savings"]
INTL = {"DE": dict(cur="EUR", fx=0.92, banks=["Rheinbrück Handelsbank", "Nordlicht Sparkasse"], phone=lambda r: f"+49 30 23125 {r.randint(0, 999):03d}", iban="DE00ZZBK%014d", ibl=14, bic="ZZBKDE22"),
        "FR": dict(cur="EUR", fx=0.92, banks=["Banque Valmont", "Caisse Lorraine d'Épargne"], phone=lambda r: f"+33 1 99 00 {r.randint(0, 99):02d} {r.randint(0, 99):02d}", iban="FR00ZZBK%019d", ibl=19, bic="ZZBKFRPP"),
        "GB": dict(cur="GBP", fx=0.79, banks=["Thamesgate Bank", "Pennine Building Society"], phone=lambda r: f"+44 20 7946 0{r.randint(0, 999):03d}", iban="GB00ZZBK%014d", ibl=14, bic="ZZBKGB2L"),
        "CA": dict(cur="CAD", fx=1.36, banks=["Maple Crest Credit Union", "Northpoint Canadian Trust"], phone=lambda r: f"+1 416 555 01{r.randint(0, 99):02d}", iban=None, ibl=9, bic="ZZBKCATT")}
ROLES2 = ["Accounts Receivable", "Billing Manager", "Controller", "Office Manager", "Finance Coordinator"]
GREET = ["Hello", "Hi", "Good morning", "Dear Accounts Payable", "Hi team", "Hello AP team", "Hi there", "Afternoon", "Dear Sir or Madam", "Greetings"]
CLOSE = ["Regards", "Thanks", "Best", "Kind regards", "Cheers", "Sincerely", "Many thanks", "Thank you", "Best regards", "Respectfully", "Thx", "With thanks"]
SIGSTYLE = ["full block (name, title, company, phone)", "name and company only", "first name only", "initials only", "name, phone", "corporate banner with confidentiality notice", "name, title, address block", "none"]
DEVICE = [("desktop", 60), ("iphone", 17), ("android", 10), ("outlook_mobile", 8), ("none", 5)]
REGISTER = [("formal", 24), ("terse", 22), ("chatty", 18), ("non_native", 12), ("portal_notification", 8), ("neutral", 16)]
HABITS = ["uses 'pls' and 'thx'", "writes in short bulleted lines", "long polite paragraphs", "ALL CAPS subject lines", "no greeting, starts with the invoice number", "adds a weekly 'hope you are well' opener",
          "uses ellipses...", "writes numbers with the currency code (USD 1,234.00)", "always refers to the PO first", "lowercase, no punctuation habit", "always includes remit-to line", "never uses contractions"]


def fake_bank(r, country, vid, salt):
    if country == "US":
        return {"bank_name": r.choice(US_BANKS), "routing_or_iban": "999%06d" % r.randint(0, 999999), "account": "0099%07d" % r.randint(0, 9999999), "swift": None, "country": "US"}
    c = INTL[country]
    if country == "CA":
        return {"bank_name": r.choice(c["banks"]), "routing_or_iban": "99999-999", "account": "0099%09d" % r.randint(0, 999999999), "swift": c["bic"], "country": "CA"}
    iban = c["iban"] % r.randint(0, 10 ** c["ibl"] - 1)
    return {"bank_name": r.choice(c["banks"]), "routing_or_iban": iban, "account": iban, "swift": c["bic"], "country": country}


def main():
    v1 = load(V1)
    out, pay_rows = [], []
    totals = sorted(sum(p["amount"] for p in v["payments"] if p["amount"] > 0) for v in v1)
    q1, q2 = totals[len(totals) // 3], totals[2 * len(totals) // 3]
    order = list(range(len(v1))); rng_for("intl").shuffle(order)
    intl_plan = ["DE"] * 3 + ["FR"] * 2 + ["GB"] * 3 + ["CA"] * 4
    intl = {order[i]: intl_plan[i] for i in range(len(intl_plan))}
    # v2 split: ~65/35 by vendor, stratified by international + size band
    strata = {}
    for i, v in enumerate(v1):
        tot = sum(p["amount"] for p in v["payments"] if p["amount"] > 0)
        strata.setdefault((i in intl, 0 if tot < q1 else 1 if tot < q2 else 2), []).append(i)
    split_of = {}
    for key in sorted(strata):
        idx = strata[key]; rng_for("split", key).shuffle(idx)
        k = round(len(idx) * 0.35)
        for j, i in enumerate(idx): split_of[i] = "holdout" if j < k else "dev"
    used_contacts = {v["contact_name"] for v in v1}
    extra_first = ["Marta", "Devon", "Lena", "Rafael", "Noor", "Tobias", "Mei", "Andre", "Greta", "Samir", "Paloma", "Idris", "Hana", "Viktor", "Camille", "Joon"]
    extra_last = ["Ferreira", "Okonkwo", "Lindgren", "Haas", "Rahimi", "Vasquez", "Doyle", "Arslan", "Kimura", "Moretti", "Baptiste", "Nguyen"]
    for i, v in enumerate(v1):
        r = rng_for("vendor", v["vendor_id"])
        pays = v["payments"]; pos = sorted(p["amount"] for p in pays if p["amount"] > 0)
        country = intl.get(i, "US"); icfg = INTL.get(country)
        cur, fx = (icfg["cur"], icfg["fx"]) if icfg else ("USD", 1.0)
        tot = sum(pos)
        size = "small" if tot < q1 else "mid" if tot < q2 else "large"
        word = [w for w in v["legal_name"].replace(",", " ").replace(".", " ").split() if w.capitalize() in INDUSTRY]
        industry = INDUSTRY[word[0].capitalize()] if word else "general services"
        depts = {}
        for p in pays: depts[p["department"]] = depts.get(p["department"], 0) + 1
        fys = sorted({p["fiscal_year"] for p in pays})
        per_year = len(pays) / max(1, len(fys))
        cadence = "weekly" if per_year >= 40 else "monthly" if per_year >= 10 else "quarterly" if per_year >= 3 else "ad hoc"
        real_po = [p for p in pays if p["po"] and p["po"].lower() != "direct payments"]
        po_frac = len(real_po) / len(pays)
        po_policy = "always" if po_frac >= 0.8 else "never" if po_frac <= 0.2 else "mixed"
        method = "wire" if country != "US" else weighted(r, [("ACH", 60 if size != "small" else 40), ("wire", 15 if size == "large" else 5), ("check", 15 if size == "small" else 6)])
        terms = weighted(r, [(15, 8), (30, 55), (45, 15), (60, 12 if size == "large" else 6)])
        med = pos[len(pos) // 2] * fx
        spread = {"p25": round(pos[len(pos) // 4] * fx, 2), "p75": round(pos[3 * len(pos) // 4] * fx, 2)}
        bank = fake_bank(r, country, v["vendor_id"], "cur")
        if country == "US": bank["routing_or_iban"] = v["bank"]["routing"]; bank["account"] = "0099" + v["bank"]["account"][4:]
        phone = icfg["phone"](r) if icfg else v["phone"]
        history = []
        if r.random() < 0.28:
            old = fake_bank(r, country, v["vendor_id"], "old")
            when = date(2021, 3, 1) + timedelta(days=r.randint(0, 1700))
            history.append({"changed_at": iso(when), "from": old, "to": bank, "verified_by": "callback to number on file", "ticket": f"BC-{when.year}-{r.randint(100, 999):04d}"[:12], "simulated": True})
        fn, ln = None, None
        while fn is None or f"{fn} {ln}" in used_contacts:
            fn, ln = r.choice(extra_first), r.choice(extra_last)
        used_contacts.add(f"{fn} {ln}")
        first = v["contact_name"].split()[0].lower()
        second = {"name": f"{fn} {ln}", "role": r.choice(ROLES2), "email": f"{fn.lower()}.{ln.lower()}@{v['domain']}", "authorized_for_bank_changes": r.random() < 0.6}
        biz_init = "".join(w[0] for w in v["legal_name"].split()[:2]).lower()
        freemail = size == "small" and r.random() < 0.35
        seqstyle = r.choice(["INV-{seq:05d}", "{yy}-{seq:04d}", "SI{seq:06d}", "A{seq:05d}", "{seq}", "INV{yy}{seq:04d}", "{pfx}-{seq:04d}"])
        pfx = "".join(c for c in v["legal_name"].upper() if c.isalpha())[:3]
        voice = {"register": weighted(r, REGISTER), "greeting": r.choice(GREET), "closing": r.choice(CLOSE), "signature_style": r.choice(SIGSTYLE),
                 "device": weighted(r, DEVICE), "habit": r.choice(HABITS), "avg_words": r.choice([25, 45, 70, 110, 160])}
        vm = {
            "vendor_id": v["vendor_id"], "in_master": True, "split": split_of[i], "legal_name": v["legal_name"], "name_variants": v["name_variants"], "domain": v["domain"],
            "industry": industry, "industry_basis": {"name_word": word[0] if word else None, "buyer_departments": sorted(depts, key=depts.get, reverse=True)[:3]},
            "size_band": size, "country": country, "currency": cur, "fx_rate_simulated": fx,
            "payment_method_on_file": method, "payment_terms_days": terms, "invoice_cadence": cadence, "po_policy": po_policy,
            "typical_amount": round(med, 2), "typical_amount_usd": round(pos[len(pos) // 2], 2), "amount_spread": spread,
            "active_years": [fys[0], fys[-1]], "payment_count": len(pays),
            "tax_id": {"status": r.choice(["W-9 on file"] * 5 + ["W-9 expired"]) if country == "US" else ("W-8BEN-E on file" if country != "CA" else "W-8BEN-E on file"),
                       "id": "99-%07d" % r.randint(0, 9999999), "fake": True},
            "preferred_contact_channel": weighted(r, [("email", 70), ("portal", 18), ("phone then email", 12)]),
            "primary_contact": {"name": v["contact_name"], "email": f"{first}@{v['domain']}", "role": "Billing"},
            "second_contact": second,
            "freemail_contact": ({"email": f"{first}.{v['contact_name'].split()[1].lower()}.{biz_init}@{r.choice(FREEMAIL)}", "note": "small vendor that sometimes writes from a personal mailbox; present in email history"} if freemail else None),
            "phone_on_file": phone, "bank_on_file": bank, "bank_change_history": history,
            "last_bank_change": history[-1]["changed_at"] if history else None,
            "invoice_number_style": {"pattern": seqstyle, "prefix": pfx},
            "voice": voice, "line_items": LINE_ITEMS.get(industry, LINE_ITEMS["consulting"]),
            "lookalikes": v["lookalikes"],
            "provenance": {"real": ["legal_name_pattern(from real payee spellings)", "payments(amount,voucher,po,fiscal_year,department)"],
                           "derived": ["industry", "size_band", "typical_amount", "amount_spread", "invoice_cadence", "po_policy", "active_years", "payment_count"],
                           "simulated": ["payment_terms_days", "payment_method_on_file", "bank_change_history", "preferred_contact_channel", "voice", "invoice_number_style", "payment dates", "fx_rate_simulated", "country/currency assignment"],
                           "fabricated": ["legal_name", "domain", "phone_on_file", "contacts", "bank_on_file", "tax_id"]}}
        rr = rng_for("infra", v["vendor_id"])
        vm["mailer"] = rr.choice(["Microsoft Outlook 16.0", "Apple Mail (2.3774)", "Gmail", "Zoho Mail", "Mozilla Thunderbird 115", "Microsoft Outlook for iOS", "Roundcube Webmail", "Outlook Web App"])
        vm["domain_registered"] = iso(date(2004, 1, 1) + timedelta(days=rr.randint(0, 6200)))   # simulated
        vm["provenance"]["simulated"] += ["mailer", "domain_registered"]
        out.append(vm)
        # ---- simulated payment dates + invoice numbers (default timing model; ERP-fitted model unavailable)
        rows = []
        for p in pays:
            lo, hi = fy_bounds(p["fiscal_year"])
            hi = min(hi, ANCHOR - timedelta(days=terms + 8)); lo = min(lo, hi - timedelta(days=1))
            if p["po_date"]:
                pd = date.fromisoformat(p["po_date"])
                if lo < pd + timedelta(days=7) < hi: lo = pd + timedelta(days=7)
            days = [lo + timedelta(days=k) for k in range((hi - lo).days + 1)]
            wts = []
            for d in days:
                w = [1.0, 1.1, 1.1, 1.0, 0.8, 0.05, 0.03][d.weekday()]
                last = calendar.monthrange(d.year, d.month)[1]
                w *= 2.2 if d.day >= last - 2 else 1.3 if d.day <= 2 else 1.0
                wts.append(w)
            inv = weighted(r, list(zip(days, wts)))
            due = inv + timedelta(days=terms)
            paid = due + timedelta(days=round(r.gauss(-1.5, 4.5)))
            paid = max(paid, inv + timedelta(days=3))
            if method in ("ACH", "wire"):
                paid = next_weekday(paid)
                if r.random() < 0.8: paid += timedelta(days=(3 - paid.weekday()) % 7)   # ACH run on Thursday
            paid = min(paid, ANCHOR)
            rows.append({"vendor_id": v["vendor_id"], "voucher": p["voucher"], "po_number": p["po"] if p["po"] and p["po"].lower() != "direct payments" else None, "fiscal_year": p["fiscal_year"],
                         "po_date": p["po_date"], "amount": round(p["amount"] * fx, 2), "amount_usd": p["amount"], "currency": cur, "name_as_paid": p["name_as_paid"], "department": p["department"],
                         "invoice_date": iso(inv), "due_date": iso(due), "paid_date": iso(paid),
                         "doc_type": "credit_memo" if p["amount"] < 0 else "zero_amount" if p["amount"] == 0 else "invoice"})
        rows.sort(key=lambda x: (x["invoice_date"], x["voucher"]))
        seq = r.randint(100, 4000); yy = lambda d: d[2:4]
        for row in rows:
            seq += r.choice([1, 1, 1, 2, 3])
            pat = seqstyle
            row["invoice_number"] = ("CM-" if row["doc_type"] == "credit_memo" else "") + pat.format(seq=seq, yy=yy(row["invoice_date"]), pfx=pfx)
            row["provenance"] = {"real": ["voucher", "po_number", "fiscal_year", "po_date", "amount_usd", "name_as_paid", "department"],
                                 "simulated": ["invoice_date", "due_date", "paid_date", "invoice_number", "currency conversion"], "dates_simulated": True,
                                 "date_model": "defaults: weekday-weighted, month-end spike, net terms + N(-1.5,4.5) day lag, Thursday ACH runs (ERP-fitted model unavailable)"}
        vm["invoice_number_style"]["last_seq"] = seq
        vm["last_invoice_number"] = rows[-1]["invoice_number"] if rows else None
        pay_rows += rows
    # ---- phantom (unregistered) suppliers: used by the fake-onboarding / phantom-vendor scenarios
    A = ["Brightwater", "Copperfield", "Dunmore", "Elmstead", "Fairhaven", "Glenrock", "Hartwell", "Ivybridge", "Kingsmere", "Larkspur", "Millbrook", "Northcote", "Oakhurst", "Pennywell", "Quillfeather", "Ravenscroft", "Stonebridge", "Thornfield", "Upland", "Vale", "Westmoor", "Yewdale", "Ashgrove", "Blackmere"]
    B = ["Contracting", "Services", "Solutions", "Industries", "Facility Care", "Maintenance", "Technical", "Supplies"]
    for k in range(24):
        r = rng_for("phantom", k)
        name = f"{A[k]} {r.choice(B)} LLC"
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower().replace(" llc", "")).strip("-")
        out.append({"vendor_id": f"PH{k + 1:03d}", "in_master": False, "split": "holdout" if k % 3 == 0 else "dev", "legal_name": name, "name_variants": [name], "domain": f"{slug}.example",
                    "industry": "unknown", "size_band": "unknown", "country": "US", "currency": "USD", "typical_amount": 0.0, "typical_amount_usd": 0.0, "payment_count": 0,
                    "bank_on_file": None, "bank_change_history": [], "phone_on_file": None, "primary_contact": {"name": f"{r.choice(extra_first)} {r.choice(extra_last)}", "email": f"accounts@{slug}.example", "role": "Billing"},
                    "po_policy": "n/a", "voice": {"register": r.choice(["formal", "neutral", "chatty"]), "device": "desktop"}, "lookalikes": [],
                    "provenance": {"fabricated": ["everything: this supplier does not exist in the vendor master by design"]}})
    import re as _re
    dump(out, V2); dump_jsonl(pay_rows, PAYMENTS)
    real = [x for x in out if x["in_master"]]
    from collections import Counter
    print(len(real), "vendors +", len(out) - len(real), "phantoms;", len(pay_rows), "payments;",
          "split", Counter(x["split"] for x in real), "| intl", Counter(x["country"] for x in real),
          "| size", Counter(x["size_band"] for x in real), "| po_policy", Counter(x["po_policy"] for x in real),
          "| cadence", Counter(x["invoice_cadence"] for x in real), "| bank history", sum(bool(x["bank_change_history"]) for x in real), "| freemail", sum(bool(x["freemail_contact"]) for x in real))


import re
if __name__ == "__main__":
    main()
