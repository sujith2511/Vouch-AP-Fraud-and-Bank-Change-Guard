"""Simulated web layer for the FICTIONAL v2 vendors. Nothing here touches the internet.

web_verify.verify_vendor_web() skips fictional (.example) vendors, so the web-verification path is never exercised on the eval set.
This module builds a deterministic "directory" of official phones/sites from data/v2/vendors.v2.json, and a replay `post` that answers
with Bright Data-shaped SERP JSON from that directory, so the REAL web_verify.verify_vendor_web() and parse() run unchanged on it.

EVERYTHING produced here is SIMULATED and says so: every result carries "simulated": true. The directory is derived from the vendor
record (official phone = phone on file), so it shows the plumbing and the guard, it is NOT evidence about how the live web behaves.

How the unchanged verify_vendor_web is reached: it returns 'not_applicable' for reserved TLDs and 'not_configured' without keys, so a
fictional domain `x.example` is mapped to the non-reserved placeholder `x.simweb` (nothing resolves it) and dummy keys are set for the
duration of the call only, then restored. The mapping is undone in the returned result.
"""
import contextlib, json, os, urllib.parse, zlib

from . import web_verify
from .llm_agent import LLMAgent

VENDORS = "data/v2/vendors.v2.json"
SIM_TLD = ".simweb"
NOTE = "SIMULATED web lookup from the fictional vendor directory; not a live search"
_dirs = {}


def sim_domain(domain):
    d = (domain or "").lower().rstrip(".")
    return d[:-len(".example")] + SIM_TLD if d.endswith(".example") else d


def real_domain(domain):
    return domain[:-len(SIM_TLD)] + ".example" if (domain or "").endswith(SIM_TLD) else domain


def build_directory(vendors_path=None):
    """{sim_domain: {vendor_id, name, domain, official_phone, official_site}} for registered v2 vendors."""
    path = vendors_path or VENDORS
    if path not in _dirs:
        out = {}
        for v in json.load(open(path)):
            if not v.get("in_master") or not v.get("phone_on_file"):
                continue
            sd = sim_domain(v["domain"])
            out[sd] = {"vendor_id": v["vendor_id"], "name": v["legal_name"], "domain": v["domain"], "sim_domain": sd,
                       "official_phone": v["phone_on_file"], "official_site": f"https://www.{sd}/"}
        _dirs[path] = out
    return _dirs[path]


def serp_for(entry):
    """Bright Data-shaped Google SERP (brd_json=1) for one vendor. The layout varies by vendor (business listing / knowledge panel /
    snippet on the vendor's own site) so parse() is exercised on each; a third-party page with a different number is always present
    and must never count as official."""
    sd, phone, site = entry["sim_domain"], entry["official_phone"], entry["official_site"]
    h = zlib.crc32(entry["vendor_id"].encode())
    decoy = f"(415) 555-{1000 + h % 8000:04d}"
    if decoy == phone:
        decoy = "(415) 555-9999"
    organic = [{"link": f"{site}contact", "title": f"Contact {entry['name']}", "description": "Reach our accounts receivable team."},
               {"link": f"https://www.bizlistings.simweb/{sd}", "title": f"{entry['name']} - business listing",
                "description": f"Phone: {decoy}. Reviews and hours."}]
    serp = {"general": {"search_engine": "google", "query": f"{entry['name']} {sd} phone number"}, "organic": organic}
    layout = h % 3
    if layout == 2 and not web_verify.phones_in(phone):
        layout = 0          # the snippet parser only reads US-style numbers; international listings come via the business listing
    if layout == 0:
        serp["snack_pack"] = [{"title": entry["name"], "phone": phone, "link": site, "maps_link": f"https://maps.google.simweb/?q={sd}"}]
    elif layout == 1:
        serp["knowledge"] = {"title": entry["name"], "link": site, "facts": [{"predicate": "Phone", "title": "Phone", "value": [{"text": phone}]}]}
    else:
        organic.insert(0, {"link": site, "title": f"{entry['name']} - official site", "description": f"Call us: {phone}. Billing questions welcome."})
    return serp


def make_post(directory=None):
    """A `post(url, timeout) -> (status, json)` replay for web_verify.verify_vendor_web: answers from the simulated directory.
    Unknown vendors get an empty 200 SERP (the real function then reports status 'empty')."""
    directory = directory if directory is not None else build_directory()

    def post(url, timeout=60.0):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("q", [""])[0]
        for sd, entry in directory.items():
            if sd in q:
                return 200, serp_for(entry)
        return 200, {"organic": []}
    return post


@contextlib.contextmanager
def _sim_keys():
    """verify_vendor_web insists on configured keys. Set dummies only for the call, never overriding real ones, then restore."""
    saved = {k: os.environ.get(k) for k in ("BRIGHT_DATA_API_KEY", "BRIGHT_DATA_SERP_ZONE")}
    os.environ.setdefault("BRIGHT_DATA_API_KEY", "simulated")
    os.environ.setdefault("BRIGHT_DATA_SERP_ZONE", "simulated")
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v


def simulated_verify(vendor, email_text="", post=None):
    """web_verify.verify_vendor_web (unchanged) against the simulated directory. Always returns simulated=True."""
    v = {**vendor, "domain": sim_domain(vendor.get("domain"))}
    with _sim_keys():
        r = web_verify.verify_vendor_web(v, email_text, post=post or make_post())
    for k in ("official_site", "query"):
        if isinstance(r.get(k), str): r[k] = r[k].replace(SIM_TLD, ".example")
    if "sources" in r: r["sources"] = [str(s).replace(SIM_TLD, ".example") for s in r["sources"]]
    return {**r, "simulated": True, "note": NOTE}


class SimWebMixin:
    """Overrides LLMAgent._web_check: fictional vendors are looked up through the simulated layer instead of being skipped.
    Real (non-reserved) domains still go through the normal path, so mixing this in never hides a live lookup."""
    def _web_check(self, item, client):
        v, e = item["vendor"] or {}, item["email"] or {}
        if not web_verify.is_fictional(v.get("domain")) or v.get("domain") == "unknown.invalid":
            return super()._web_check(item, client)
        phone = None
        try:
            phone = ((client.read_vendor_history(item["vendor_id"], 1) or {}).get("vendor") or {}).get("phone")
        except Exception:
            pass
        return simulated_verify({"name": v.get("name"), "domain": v.get("domain"), "phone": phone}, f"{e.get('subject', '')}\n{e.get('body', '')}")


class SimulatedWebLLMAgent(SimWebMixin, LLMAgent):
    pass


def with_simulated_web(agent_cls):
    """Same agent class, simulated web layer mixed in."""
    if issubclass(agent_cls, SimWebMixin): return agent_cls
    return type(agent_cls.__name__ + "SimWeb", (SimWebMixin, agent_cls), {})


# ---------------------------------------------------------------- a stub "LLM" so the whole path can be verified without a key
class _Block:
    def __init__(self, **kw): self.__dict__.update(kw)


class StubLLM:
    """Stands in for the Anthropic client: always submits the same decision, no network. For verification ONLY (never a real result)."""
    def __init__(self, verdict="legit"):
        self.verdict, self.messages = verdict, self

    def create(self, **kw):
        block = _Block(type="tool_use", id="stub", name="submit_decision",
                       input={"kind": "propose", "verdict": self.verdict, "confidence": 0.9, "reasons": ["stub agent: fixed verdict"], "question": ""})
        return _Block(content=[block], stop_reason="tool_use", usage=_Block(input_tokens=0, output_tokens=0))


def _no_shield(subject, body):
    return {"status": "not_configured"}


class StubLLMAgent(LLMAgent):
    """The real LLMAgent code (render, _guard) with a stub in place of the model: `legit` for everything, so any stricter outcome comes from
    the code-level guard. No web lookup for fictional vendors (the default). --agent vouch.web_sim:StubLLMAgent"""
    def __init__(self, verdict="legit"):
        super().__init__(anthropic_client=StubLLM(verdict), model="stub", shield=_no_shield)


class StubWebAgent(SimWebMixin, StubLLMAgent):
    """Same stub with the simulated web layer: --agent vouch.web_sim:StubWebAgent (or StubLLMAgent with --web sim)."""
