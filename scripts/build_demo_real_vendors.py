"""Build data/v2/demo_real_vendors.json: a handful of LARGE PUBLIC companies for the live-web-verification demo.

For each company: legal name + phone from SEC EDGAR (data.sec.gov submissions API), website and the phone(s) shown on the
company's own contact page(s), whether they match, and the company's REAL payments from the SF Controller dataset matched by
EXACT payee spelling. Nothing is fabricated: missing values are null with a reason. Bank details are fake TEST values.

DEMO ONLY. Never loaded into dev/holdout eval, and no email in any dataset impersonates these companies.

SEC fair-access rules require a descriptive User-Agent with a contact email; set VOUCH_SEC_CONTACT (default below).
    python scripts/build_demo_real_vendors.py
"""
import hashlib, json, os, re, statistics, time
from datetime import datetime, timezone

import requests

CONTACT = os.environ.get("VOUCH_SEC_CONTACT", "shringiayushi08@gmail.com")
SEC_UA = {"User-Agent": f"Vouch CalHacks13 demo-data (contact: {CONTACT})", "Accept-Encoding": "gzip, deflate"}
WEB_UA = {"User-Agent": f"Mozilla/5.0 (compatible; VouchDemoDataBot/1.0; contact {CONTACT})"}
PHONE = re.compile(r"(?:\+?1[\s.\-]?)?\(?\b\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b")
SODA = "https://data.sf.gov/resource"

# exact SF payee spelling(s) that equal the SEC registrant's name. Related spellings are reported, NOT included.
COMPANIES = [
    {"cik": "0000068505", "spellings": ["MOTOROLA SOLUTIONS INC"], "site": "https://www.motorolasolutions.com",
     "contact_pages": [("general contact page", "https://www.motorolasolutions.com/en_us/contact-us.html"),
                       ("investor contact page", "https://www.motorolasolutions.com/investors/contact-us.html")]},
    {"cik": "0000789019", "spellings": ["MICROSOFT CORP"], "site": "https://www.microsoft.com",
     "contact_pages": [("support contact page", "https://support.microsoft.com/contactus")]},
    {"cik": "0001108524", "spellings": ["SALESFORCE.COM INC"], "site": "https://www.salesforce.com",
     "contact_pages": [("company contact page", "https://www.salesforce.com/company/contact-us/")]},
    {"cik": "0001341439", "spellings": ["ORACLE CORP"], "site": "https://www.oracle.com",
     "contact_pages": [("corporate contact page", "https://www.oracle.com/corporate/contact/")]},
]


def digits(p):
    d = re.sub(r"\D", "", p or "")
    return d[-10:] if len(d) >= 10 else d


def text_of(html):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))


def sec_record(cik):
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    r = requests.get(url, headers=SEC_UA, timeout=30); r.raise_for_status()
    d = r.json(); time.sleep(0.3)   # well under SEC's 10 req/s limit
    return {"cik": cik, "name": d["name"], "tickers": d.get("tickers"), "entity_type": d.get("entityType"),
            "phone_raw": d.get("phone"), "phone_digits": digits(d.get("phone")), "edgar_website_field": d.get("website") or None,
            "business_address": d["addresses"]["business"], "source_url": url}


def website_record(base, sec_name):
    try:
        r = requests.get(base, headers=WEB_UA, timeout=30)
        title = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I)
        t = title.group(1).strip() if title else None
        word = re.split(r"[ ,.]+", sec_name)[0].lower()
        ok = r.status_code == 200 and bool(t) and word in t.lower()
        return {"url": base, "final_url": r.url, "http_status": r.status_code, "page_title": t, "verified": ok,
                "source": "company's well-known domain (EDGAR website field is empty)",
                "note": None if ok else f"NOT verified: HTTP {r.status_code}, page did not load as the company homepage (blocked); URL is the well-known domain, unconfirmed by fetch"}
    except Exception as e:   # noqa: BLE001
        return {"url": base, "http_status": None, "verified": False, "error": repr(e)[:120], "source": "company's well-known domain (fetch failed)"}


def contact_record(label, url):
    out = {"label": label, "url": url, "http_status": None, "phones": [], "note": None}
    try:
        r = requests.get(url, headers=WEB_UA, timeout=30)
    except Exception as e:   # noqa: BLE001
        out["note"] = f"fetch failed: {e!r}"[:160]; return out
    out["http_status"] = r.status_code
    txt = text_of(r.text); seen = set()
    for m in PHONE.finditer(txt):
        n = m.group(0)
        if digits(n) in seen: continue
        seen.add(digits(n))
        before = txt[max(0, m.start() - 110):m.start()]
        out["phones"].append({"number": n, "digits": digits(n), "context": txt[max(0, m.start() - 70):m.end() + 25].strip(),
                              "looks_like_headquarters": bool(re.search(r"headquarters|corporate office|main office", before, re.I))})
    if r.status_code != 200:
        out["note"] = (f"HTTP {r.status_code}: the site blocked the request and served an error page; any number below comes from that error page's own "
                       "text, not the contact page, so treat it as LOW confidence. No attempt was made to bypass the block.")
    elif not out["phones"]:
        out["note"] = "no phone number in the server-rendered HTML (page is likely JavaScript-rendered); nothing was guessed"
    return out


def sf_payments(spellings):
    """Complete history for these EXACT payee spellings, plus related spellings found (reported, not included)."""
    where = "vendor in (" + ",".join("'" + s.replace("'", "''") + "'" for s in spellings) + ")"
    rows = requests.get(f"{SODA}/n9pm-xkyq.json", timeout=120, params={
        "$select": "fiscal_year,department,purchase_order,vendor,vouchers_paid,voucher", "$where": where, "$limit": 50000}).json()
    pos = requests.get(f"{SODA}/p5r5-fd7g.json", timeout=120, params={
        "$select": "purchase_order,purchase_order_date", "$where": where, "$limit": 50000}).json()
    podate = {p["purchase_order"]: p["purchase_order_date"][:10] for p in pos if p.get("purchase_order_date") and "direct payments" not in p["purchase_order"].lower()}
    pays = [{"voucher": r.get("voucher"), "po": r.get("purchase_order"), "fiscal_year": int(r["fiscal_year"]), "po_date": podate.get(r.get("purchase_order")),
             "amount": round(float(r["vouchers_paid"]), 2), "name_as_paid": r["vendor"], "department": r.get("department")}
            for r in rows if r.get("vouchers_paid") not in (None, "")]
    pays.sort(key=lambda p: (p["fiscal_year"], p["po_date"] or "", p["voucher"] or ""))
    return pays


def related_spellings(key_word, exclude):
    rows = requests.get(f"{SODA}/n9pm-xkyq.json", timeout=120, params={
        "$select": "vendor,count(*) as n", "$where": f"upper(vendor) like '%{key_word}%'", "$group": "vendor", "$order": "n DESC", "$limit": 8}).json()
    return [{"payee": r["vendor"], "rows": int(r["n"])} for r in rows if r["vendor"] not in exclude]


def main(out="data/v2/demo_real_vendors.json"):
    companies = []
    for i, c in enumerate(COMPANIES, 1):
        sec = sec_record(c["cik"])
        site = website_record(c["site"], sec["name"])
        pages = [contact_record(l, u) for l, u in c["contact_pages"]]
        all_phones = [p for pg in pages for p in pg["phones"]]
        match_pages = [pg["label"] for pg in pages if any(p["digits"] == sec["phone_digits"] for p in pg["phones"])]
        if not all_phones:
            match = {"matches_sec_phone": None, "reason": "no phone number could be read from the company's contact page(s); not guessed"}
        elif match_pages:
            match = {"matches_sec_phone": True, "matched_on": match_pages,
                     "reason": "SEC phone appears on the company's own page; other numbers on the pages (sales/support/investor lines) differ and are listed"}
        else:
            low = any(pg["http_status"] != 200 for pg in pages)
            match = {"matches_sec_phone": False, "confidence": "low" if low else "normal",
                     "reason": "no phone on the company's contact page(s) equals the SEC phone" + ("; the page was blocked so this rests on an error page's text" if low else "")}
        pays = sf_payments(c["spellings"])
        pos_amts = [p["amount"] for p in pays if p["amount"] > 0]
        h = int(hashlib.sha256(f"demo-real-{c['cik']}".encode()).hexdigest(), 16)
        key = re.split(r"[ ,.]", sec["name"])[0].upper()
        companies.append({
            "demo_vendor_id": f"DEMO-R{i}", "demo_only": True, "exclude_from_eval": True, "split": None,
            "legal_name": sec["name"], "sec": sec, "website": site,
            "contact_pages": pages, "phone_check": match,
            "sf_payments": {
                "exact_payee_spellings_used": c["spellings"],
                "found": bool(pays), "count": len(pays), "total_paid": round(sum(p["amount"] for p in pays), 2),
                "median_positive_amount": statistics.median(pos_amts) if pos_amts else None,
                "fiscal_years": sorted({p["fiscal_year"] for p in pays}),
                "note": None if pays else "no payments under these exact spellings in the SF dataset; none fabricated",
                "related_payee_spellings_NOT_included": related_spellings(key, set(c["spellings"])),
                "payments": pays},
            "bank": {"routing": "999%06d" % (h % 10**6), "account": "TEST%07d" % ((h >> 16) % 10**7), "note": "FAKE test values"},
            "fabricated_fields": ["bank"],
        })
        print(f"{sec['name']}: sec phone {sec['phone_raw']}, match={match['matches_sec_phone']}, SF payments={len(pays)}")
    doc = {"_notice": "DEMO ONLY. Real public companies for the live web-verification demo. Never used in dev/holdout eval; no email in any dataset "
                      "impersonates these companies (tests enforce this). The live attack email uses a fictional vendor. Bank details are fake TEST values.",
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "sources": {"sec": "https://data.sec.gov/submissions/ (public domain US government data; descriptive User-Agent with contact email sent per SEC fair-access rules)",
                       "company_pages": "each company's own website, fetched once per page",
                       "payments": "SF Controller 'Vendor Payments (Vouchers)' n9pm-xkyq + 'Purchase Order Summary' p5r5-fd7g, PDDL 1.0 (data.sf.gov)"},
           "companies": companies}
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(doc, open(out, "w"), indent=1)
    print("wrote", out, f"({os.path.getsize(out) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
