"""Rename every real vendor to a deterministic fictional name, including the sender domains and dnstwist lookalikes derived
from it, so nothing real is published. The real->fictional map is never written to disk.
    python scripts/fictionalize.py data/local/vendors.real.json data/vendors.json [emails_in emails_out]
Spelling mess is preserved: each real variant maps to a fictional variant with the same casing / suffix habit."""
import hashlib, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from build_lookalikes import add_lookalikes

A = ["Cobalt", "Juniper", "Summit", "Alder", "Pinnacle", "Lumen", "Granite", "Willow", "Tidewater", "Ember", "Quarry", "Beacon", "Marlow", "Sable", "Fulton", "Orchid", "Kestrel", "Bramble", "Vantage", "Halcyon"]
B = ["Ridge", "Works", "Supply", "Dynamics", "Partners", "Haulage", "Labs", "Industrial", "Analytics", "Logistics", "Fabrication", "Systems", "Textiles", "Controls"]
C = ["LLC", "Inc.", "Co.", "Group", "Corp."]
SUFFIX = re.compile(r"[\s,]+(inc\.?|incorporated|llc|l l c|corp\.?|corporation|co\.?|company|ltd|lp|llp)$", re.I)


def fake_name(vid):
    h = int(hashlib.sha256(("demo" + vid).encode()).hexdigest(), 16)
    return f"{A[h % len(A)]} {B[(h >> 8) % len(B)]}", C[(h >> 16) % len(C)]


def main(vendors_in, vendors_out, emails_in=None, emails_out=None):
    vendors = json.load(open(vendors_in)); rep = {}
    for v in vendors:
        base, suf = fake_name(v["vendor_id"]); legal = f"{base} {suf}"
        def variant(real):
            has_suffix = bool(SUFFIX.search(real))
            t = f"{base} {suf}" if has_suffix else base
            return t.upper() if real.isupper() else t
        variants = sorted(set(v["name_variants"] + [v["legal_name"]]), key=len, reverse=True)
        for real in variants: rep[real] = variant(real)
        v["legal_name"] = rep[v["legal_name"]] if v["legal_name"] in rep else legal
        v["name_variants"] = list(dict.fromkeys(rep[r] for r in v["name_variants"]))
        v["domain"] = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") + f"-{suf.lower().strip('.')}.example"
        for p in v["payments"]: p["name_as_paid"] = rep.get(p["name_as_paid"], base)
    add_lookalikes(vendors)
    json.dump(vendors, open(vendors_out, "w"), indent=1)
    pats = [(re.compile(re.escape(o), re.I), n) for o, n in sorted(rep.items(), key=lambda kv: -len(kv[0]))]
    if emails_in and Path(emails_in).exists():
        dom = {}
        with open(emails_out, "w") as fh:
            for l in open(emails_in):
                e = json.loads(l)
                for k in ("subject", "body"):
                    for p, n in pats: e[k] = p.sub(n, e[k])
                fh.write(json.dumps(e) + "\n")
    print("fictionalized", len(vendors), "vendors ->", vendors_out)


if __name__ == "__main__":
    main(*sys.argv[1:])
