"""Live demo of the Bright Data vendor check on the team's demo-only real companies (Ayushi's SEC EDGAR file).

No email is written in these companies' names (see the file's notice). The demo shows:
  1. Bright Data finds the company's official phones and website on the live web;
  2. whether the phone the company registered with the SEC is among them, and whether the site is on the company domain;
  3. optionally, whether a phone number you type in (say, one a "vendor" asked you to call) is one they list.

    python scripts/demo_web_verify.py data/v2/demo_real_vendors.json
    python scripts/demo_web_verify.py data/v2/demo_real_vendors.json --company motorola --check-phone "(847) 555-0100"

Costs one Bright Data search per company. Needs BRIGHT_DATA_API_KEY and BRIGHT_DATA_SERP_ZONE in .env.
"""
import argparse, json, sys, urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # run from anywhere without installing the package

from vouch import web_verify as wv          # noqa: E402
from vouch.llm_agent import load_env        # noqa: E402


def as_vendor(company):
    """The file has no 'domain' field on purpose; the domain comes from the verified website URL."""
    host = urllib.parse.urlparse(company["website"]["url"]).hostname or ""
    return {"name": company["legal_name"], "domain": host.removeprefix("www."), "phone": company["sec"]["phone_raw"]}


def fmt(digits):
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}" if digits and len(digits) == 10 else str(digits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="the demo-only companies file")
    ap.add_argument("--company", help="substring of the company name (default: all)")
    ap.add_argument("--check-phone", help="a phone number to check against what the web lists for the company")
    a = ap.parse_args()
    load_env()
    if not wv.is_configured():
        raise SystemExit("set BRIGHT_DATA_API_KEY and BRIGHT_DATA_SERP_ZONE in .env")
    companies = json.load(open(a.path))["companies"]
    if a.company:
        companies = [c for c in companies if a.company.lower() in c["legal_name"].lower()]
    for c in companies:
        v = as_vendor(c)
        r = wv.verify_vendor_web(v, a.check_phone or "")
        print(f"\n== {v['name']}  ({v['domain']})")
        print(f"   SEC-registered phone: {v['phone']}   |   Bright Data lookup: {r['status']}")
        if r["status"] != "ok":
            print("   -> could not verify online: a human must check (never assumed fine)")
            continue
        print(f"   official site: {r['official_site']}  (on company domain: {'yes' if r['site_domain_matches_vendor'] else 'NO'})")
        print(f"   phones listed online: {', '.join(fmt(p) for p in r['official_phones']) or 'none found'}")
        on_file = r["phone_on_file_listed_online"]
        print(f"   SEC phone listed online: {'yes' if on_file else 'no' if on_file is False else 'unknown (no official phone found)'}")
        if a.check_phone:
            bad, unconfirmed = r["email_phones_not_listed_online"], r["email_phones_unconfirmed"]
            verdict = ("NOT one of their listed numbers: do not call it" if bad else
                       "could not be confirmed (no official number found): call the number on file instead" if unconfirmed else
                       "listed by the company")
            print(f"   {a.check_phone}: {verdict}")


if __name__ == "__main__":
    main()
