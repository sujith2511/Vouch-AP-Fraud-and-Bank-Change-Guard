"""verify_vendor_web: look up the REAL vendor on the public web through Bright Data's SERP API and compare what the
internet says (official phone, official website) with our vendor record and with the phone numbers in the email.

A classic bank-change fraud says "call us at <new number> to confirm". If that number is not one the web lists for
the vendor, that is a red flag a human should see.

* Fictional vendors (reserved TLDs: .example / .test / .invalid / .localhost) are 'not_applicable': no request is
  made, so the eval set stays offline and free. Real demo vendors are recognised by having a real domain.
* blocked / empty / error results are never treated as reassurance; LLMAgent._guard escalates them for real vendors.
* Results are cached per vendor for the process lifetime (one paid search per vendor per run).

Config: BRIGHT_DATA_API_KEY, BRIGHT_DATA_SERP_ZONE (a SERP API zone; Full JSON output).
Docs: https://docs.brightdata.com/scraping-automation/serp-api/parsed-json-results
"""
import os, re, urllib.parse

ENDPOINT = "https://api.brightdata.com/request"
FICTIONAL_TLDS = (".example", ".test", ".invalid", ".localhost")
# US/Canada numbers only. (?<!\d) / (?!\d) stop a 10-12 digit PO or invoice number (000053180001) from being read as a
# phone; area and exchange codes start with 2-9 under the NANP, which also keeps e.g. UK "(020) 7946 ..." out.
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?[2-9]\d{2}\)?[\s.-]?[2-9]\d{2}[\s.-]?\d{4}(?!\d)")
_cache = {}


def is_configured():
    return bool(os.environ.get("BRIGHT_DATA_API_KEY") and os.environ.get("BRIGHT_DATA_SERP_ZONE"))


def is_fictional(domain):
    return not domain or domain.lower().rstrip(".").endswith(FICTIONAL_TLDS)


def norm_phone(s):
    d = re.sub(r"\D", "", str(s or ""))
    return d[-10:] if len(d) >= 10 else None


def phones_in(text):
    return sorted({p for p in (norm_phone(m) for m in PHONE_RE.findall(text or "")) if p})


def _domain_of(url):
    host = urllib.parse.urlparse(url or "").hostname or ""
    return host.lower().removeprefix("www.")


def _result_url(o):
    """The page a search result points to. Google sometimes returns opaque redirects (https://www.google.com/goto?url=<encrypted>);
    then the real host is only in display_link ("https://www.vendor.example › en_us › contact-us")."""
    link = o.get("link") or ""
    host = urllib.parse.urlparse(link).hostname or ""
    if host.endswith("google.com") and urllib.parse.urlparse(link).path in ("/goto", "/url"):
        shown = (o.get("display_link") or "").split("›")[0].strip()
        return shown if shown.startswith("http") else None
    return link or None


def _on_domain(url, domain):
    d = _domain_of(url)
    return bool(d) and (d == domain or d.endswith("." + domain))


def _texts(v):
    """knowledge.facts[].value is a string in the docs and a list of {"text": ...} in live responses."""
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [x.get("text", "") if isinstance(x, dict) else str(x) for x in v]
    return []


def parse(serp, vendor_domain=""):
    """Pull official phones, official site and sources out of a Bright Data Google SERP (brd_json=1) response.
    Phones come from the business listing, the knowledge panel, and snippets of results ON the vendor's own domain
    (a third-party or scam page's number never counts as official)."""
    phones, sources, site = set(), [], None
    for b in serp.get("snack_pack") or []:
        if norm_phone(b.get("phone")):
            phones.add(norm_phone(b["phone"]))
            sources.append(b.get("maps_link") or b.get("link"))
        site = site or b.get("link")
    kn = serp.get("knowledge") or {}
    for f in kn.get("facts") or []:
        label = f"{f.get('predicate', '')} {f.get('title', '')}".lower()
        if "phone" in label:
            for t in _texts(f.get("value")):
                if norm_phone(t):
                    phones.add(norm_phone(t))
                    sources.append("google knowledge panel")
    for o in serp.get("organic") or []:
        url = _result_url(o)
        if vendor_domain and _on_domain(url, vendor_domain):
            for p in phones_in(f"{o.get('title', '')} {o.get('description', '')}"):
                phones.add(p)
                sources.append(url)
    organic = [u for u in (_result_url(o) for o in serp.get("organic") or []) if u]
    # official site: the knowledge panel's, else the first result on the vendor's own domain; a directory page
    # (MapQuest, Yelp) ranking first must not make a real vendor look mismatched
    on_domain = [u for u in organic if vendor_domain and _on_domain(u, vendor_domain)]
    site = kn.get("link") or (on_domain[0] if on_domain else None) or site or (organic[0] if organic else None)
    return {"official_phones": sorted(phones), "official_site": site, "sources": [s for s in sources if s] + organic[:3]}


def verify_vendor_web(vendor, email_text="", post=None, timeout=60.0):
    """vendor: {"name", "domain", "phone"}. Returns a dict with status ok | empty | blocked | error | not_configured |
    not_applicable, plus the comparisons when status is ok."""
    name, domain = vendor.get("name"), (vendor.get("domain") or "").lower()
    email_phones = phones_in(email_text)
    out = {"provider": "bright_data", "vendor": name, "email_phones": email_phones}
    if is_fictional(domain):
        return {**out, "status": "not_applicable", "note": "fictional vendor (reserved test domain); no web lookup"}
    if not is_configured():
        return {**out, "status": "not_configured"}

    key = (name, domain)
    if key not in _cache:
        query = f"{name} {domain} phone number"
        url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": query, "hl": "en", "gl": "us", "brd_json": "1"})
        try:
            status, body = (post or _httpx_post)(url, timeout)
        except Exception as ex:
            return {**out, "status": "error", "error": f"{type(ex).__name__}: {str(ex)[:200]}"}
        if status in (401, 403, 407, 429) or status >= 500:
            return {**out, "status": "blocked", "error": f"HTTP {status}"}      # not cached: may work on retry
        if status != 200 or not isinstance(body, dict):
            return {**out, "status": "error", "error": f"HTTP {status}"}
        _cache[key] = {"query": query, **parse(body, domain)}
    found = _cache[key]

    if not found["official_phones"] and not found["official_site"]:
        return {**out, "status": "empty", "query": found["query"]}
    official = set(found["official_phones"])
    on_file = norm_phone(vendor.get("phone"))
    return {
        **out, "status": "ok", "query": found["query"],
        "official_phones": found["official_phones"], "official_site": found["official_site"],
        "site_domain_matches_vendor": _on_domain(found["official_site"], domain),
        "phone_on_file_listed_online": (on_file in official) if (on_file and official) else None,
        "email_phones_not_listed_online": [p for p in email_phones if official and p not in official],
        # no official number found: phone numbers in the email cannot be confirmed (never read as "fine")
        "email_phones_unconfirmed": [p for p in email_phones if not official],
        "sources": found["sources"][:5],
    }


def _httpx_post(url, timeout):
    import httpx
    r = httpx.post(ENDPOINT, headers={"Authorization": f"Bearer {os.environ['BRIGHT_DATA_API_KEY']}"},
                   json={"zone": os.environ["BRIGHT_DATA_SERP_ZONE"], "url": url, "format": "raw"}, timeout=timeout)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None
