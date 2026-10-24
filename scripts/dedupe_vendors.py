"""Make data/vendors.json collision-free. Keeps the FIRST vendor (by id) in any collision and renames later ones.
Checks: legal name, base name (suffix stripped), domain, contact name, phone, lookalike domains (unique across all vendors and never
equal to any real vendor domain). Never touches amounts, voucher ids, banks, splits or payment records (only payee spellings follow a rename).
    python scripts/dedupe_vendors.py [data/vendors.json]"""
import hashlib, json, random, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from build_lookalikes import add_lookalikes

SUFFIX = re.compile(r"[\s,]+(inc\.?|incorporated|llc|l l c|corp\.?|corporation|co\.?|company|ltd|lp|llp|group)$", re.I)
WORDS_A = ["Cobalt", "Juniper", "Summit", "Alder", "Pinnacle", "Lumen", "Granite", "Willow", "Tidewater", "Ember", "Quarry", "Beacon", "Marlow", "Sable", "Fulton", "Orchid", "Kestrel", "Bramble", "Vantage", "Halcyon",
           "Harlow", "Ironwood", "Mesa", "Northfield", "Opal", "Prairie", "Redwood", "Silverline", "Thistle", "Umber", "Verdant", "Wexford", "Yarrow", "Zephyr", "Arbor", "Birchwood", "Cinder", "Driftwood", "Evergreen", "Foxglove"]
WORDS_B = ["Ridge", "Works", "Supply", "Dynamics", "Partners", "Haulage", "Labs", "Industrial", "Analytics", "Logistics", "Fabrication", "Systems", "Textiles", "Controls",
           "Instruments", "Mechanical", "Electric", "Hydraulics", "Dataworks", "Consulting", "Packaging", "Engineering", "Metals", "Networks", "Freightways", "Fabricators", "Robotics", "Environmental"]
FIRST = ["Dana", "Morgan", "Priya", "Luis", "Chen", "Tamika", "Oleg", "Fatima", "Jordan", "Kenji", "Rosa", "Imani", "Nikolai", "Sofia", "Hiro", "Ayo", "Marta", "Devon", "Lena", "Rafael", "Noor", "Tobias", "Mei", "Andre"]
LAST = ["Alvarez", "Okafor", "Brandt", "Nakamura", "Haddad", "Whitfield", "Castillo", "Lindqvist", "Mbeki", "Duarte", "Kowalski", "Iyer", "Petrov", "Sandoval", "Eriksen", "Ogunleye", "Moreau", "Tanaka", "Bianchi", "Novak"]


def lev(p, q):
    pr = list(range(len(q) + 1))
    for i, c in enumerate(p, 1):
        cu = [i]
        for j, d in enumerate(q, 1): cu.append(min(pr[j] + 1, cu[j - 1] + 1, pr[j - 1] + (c != d)))
        pr = cu
    return pr[-1]


def stale(v):   # lookalikes must derive from the vendor's CURRENT domain (a rename leaves the old ones behind)
    return any(lev(l["domain"].split(".")[0], v["domain"].split(".")[0]) > 6 for l in v.get("lookalikes", []))


def base_of(name): return SUFFIX.sub("", name).strip()
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def rename(v, new_base):
    old_names = sorted(set(v["name_variants"] + [v["legal_name"]]), key=len, reverse=True)
    suf_m = SUFFIX.search(v["legal_name"]); suffix = suf_m.group(0).strip(" ,") if suf_m else None
    mp = {}
    for o in old_names:
        has = bool(SUFFIX.search(o)); t = f"{new_base} {suffix}" if (has and suffix) else new_base
        mp[o] = t.upper() if o.isupper() else t
    v["legal_name"] = mp[v["legal_name"]]
    v["name_variants"] = list(dict.fromkeys(mp[n] for n in v["name_variants"]))
    tail = v["domain"].rsplit(".example", 1)[0].rsplit("-", 1)[-1]
    v["domain"] = f"{slug(new_base)}-{tail}.example"
    for p in v["payments"]: p["name_as_paid"] = mp.get(p["name_as_paid"], v["legal_name"])


def main(path="data/vendors.json"):
    vendors = json.load(open(path))
    used_base, used_dom, used_contact, used_phone = set(), set(), set(), set()
    changes = {"renamed": [], "contact": [], "phone": [], "lookalike": []}
    for v in vendors:                                   # pass 1: names + domains + contacts + phones (first vendor wins)
        b = base_of(v["legal_name"]).lower()
        if b in used_base or v["domain"] in used_dom:
            h = int(hashlib.sha256(("dedupe" + v["vendor_id"]).encode()).hexdigest(), 16)
            cands = [f"{a} {c}" for a in WORDS_A for c in WORDS_B]; random.Random(h).shuffle(cands)
            new = next(c for c in cands if c.lower() not in used_base and f"{slug(c)}-{v['domain'].rsplit('.example',1)[0].rsplit('-',1)[-1]}.example" not in used_dom)
            old = v["legal_name"]; rename(v, new); changes["renamed"].append((v["vendor_id"], old, v["legal_name"]))
            b = base_of(v["legal_name"]).lower()
        used_base.add(b); used_dom.add(v["domain"])
        if v["contact_name"] in used_contact:
            h = random.Random(int(hashlib.sha256(("c" + v["vendor_id"]).encode()).hexdigest(), 16))
            opts = [f"{f} {l}" for f in FIRST for l in LAST if f"{f} {l}" not in used_contact]; new = h.choice(opts)
            changes["contact"].append((v["vendor_id"], v["contact_name"], new)); v["contact_name"] = new
        used_contact.add(v["contact_name"])
        if v["phone"] in used_phone:
            free = [f"(415) 555-01{n:02d}" for n in range(100) if f"(415) 555-01{n:02d}" not in used_phone]
            new = free[int(hashlib.sha256(("p" + v["vendor_id"]).encode()).hexdigest(), 16) % len(free)]
            changes["phone"].append((v["vendor_id"], v["phone"], new)); v["phone"] = new
        used_phone.add(v["phone"])
    real = {v["domain"] for v in vendors}                # pass 2: lookalikes unique across vendors, never a real vendor domain
    seen = set()
    for v in vendors:
        for attempt in range(40):
            if attempt or "lookalikes" not in v or stale(v) or any(l["domain"] in seen or l["domain"] in real for l in v["lookalikes"]):
                add_lookalikes([v], seed=13 + attempt)
                if attempt: changes["lookalike"].append(v["vendor_id"]) if v["vendor_id"] not in changes["lookalike"] else None
            if not any(l["domain"] in seen or l["domain"] in real for l in v["lookalikes"]): break
        else:
            raise SystemExit(f"could not find unique lookalikes for {v['vendor_id']}")
        seen |= {l["domain"] for l in v["lookalikes"]}
    json.dump(vendors, open(path, "w"), indent=1)
    print({k: len(x) for k, x in changes.items()}); print("renamed:", changes["renamed"])


if __name__ == "__main__":
    main(*sys.argv[1:])
