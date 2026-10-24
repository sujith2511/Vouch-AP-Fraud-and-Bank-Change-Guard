"""Probe each company's own site: confirm the homepage names the company, find contact-page links, extract phone numbers with context."""
import re, sys, requests
from urllib.parse import urljoin
UA = {"User-Agent": "Mozilla/5.0 (compatible; VouchDemoDataBot/1.0; contact shringiayushi08@gmail.com)"}
PHONE = re.compile(r"(?:\+?1[\s.\-]?)?\(?\b\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b")
sites = {"Motorola Solutions": "https://www.motorolasolutions.com", "Microsoft": "https://www.microsoft.com", "Salesforce": "https://www.salesforce.com", "Oracle": "https://www.oracle.com"}
for name, base in sites.items():
    try:
        r = requests.get(base, headers=UA, timeout=30, allow_redirects=True)
    except Exception as e:
        print(name, "FETCH FAIL", repr(e)[:100]); continue
    title = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I)
    print(f"\n## {name}: {r.status_code} final={r.url} title={title.group(1).strip()[:80] if title else None}")
    links = {urljoin(r.url, m) for m in re.findall(r'href="([^"#]*contact[^"#]*)"', r.text, re.I)}
    print("   contact-ish links:", sorted(links)[:8])
