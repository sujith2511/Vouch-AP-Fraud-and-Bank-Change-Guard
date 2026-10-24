"""Normalize the SF Controller 'Vendor Payments (Vouchers)' dataset into per-vendor payment history.

Real (kept as-is, including mess): vendor name spellings, voucher ids, PO numbers, amounts (incl. credits/zeros/duplicates),
fiscal year, purchase-order date (joined from the PO Summary dataset).
Fabricated (must be fake): sender domain (.example), contact name, 555 phone, bank details (obvious test values).
"""
import argparse, hashlib, json, random, re
import pandas as pd
import requests

FIRST = ["Dana","Morgan","Priya","Luis","Chen","Tamika","Oleg","Fatima","Jordan","Kenji","Rosa","Imani","Nikolai","Sofia","Hiro","Ayo"]
LAST = ["Alvarez","Okafor","Brandt","Nakamura","Haddad","Whitfield","Castillo","Lindqvist","Mbeki","Duarte","Kowalski","Iyer"]
SUFFIX = r"\b(inc|incorporated|llc|l l c|corp|corporation|co|company|ltd|lp|llp|the)\b"

def canon(s):
    return re.sub(r"[^a-z0-9]", "", re.sub(SUFFIX, "", str(s).lower()))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vouchers", default="data/raw/sf_vouchers/vouchers.csv")
    ap.add_argument("--po", default="data/raw/sf_po/po.csv")
    ap.add_argument("--out", default="data/local/vendors.real.json")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=13)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    # Stage 1: pick candidate vendors from the (partial) bulk download. The bulk files were truncated by a
    # download timeout, so they are used ONLY for selection; stage 2 pulls complete history from the SODA API.
    v = pd.read_csv(a.vouchers, dtype=str, usecols=["Fiscal Year","Supplier & Other Non-Supplier Payees","Vouchers Paid","Non-Profit Indicator"])
    v = v.rename(columns={"Fiscal Year":"fy","Supplier & Other Non-Supplier Payees":"vendor","Vouchers Paid":"amount","Non-Profit Indicator":"nonprofit"})
    v["amount"] = pd.to_numeric(v["amount"], errors="coerce")
    v = v[v.fy.between("2020", "2026") & v.vendor.notna() & v.amount.notna() & v.nonprofit.isna()]
    v = v[~v.vendor.str.match(r"^[A-Za-z]+ [A-Z]\.? [A-Za-z]+$") & ~v.vendor.str.match(r"^[A-Za-z]+ [A-Za-z]+$")]   # drop likely individuals (two/three-word personal names)
    v["key"] = v.vendor.map(canon)
    v = v[v.key.str.len() >= 5]
    v = v[~v.vendor.str.contains(r"refund|city|county|state of|dept|department|school|district|university|employee|retire|trust|tax|bureau|\bsf\b|san francisco|\b(?:mft|lcsw|md|dds|phd|psyd|dr|esq|cpa|therapist|mfcc|horseshoeing)\b", case=False, regex=True)]
    stats = v.groupby("key").agg(n=("amount","size"), npos=("amount", lambda s: (s>0).sum()), fys=("fy","nunique"),
                                 med=("amount", lambda s: s[s>0].median()), spell=("vendor","nunique"))
    ok = stats[(stats.npos>=8)&(stats.n<=120)&(stats.fys>=2)&(stats.med.between(300,150000))]
    multi = list(ok[ok.spell>1].index); single = list(ok[ok.spell==1].index)
    rng.shuffle(multi); rng.shuffle(single)
    cand = multi[:40] + single[:60]
    spellings = {k: sorted(v[v.key == k].vendor.unique()) for k in cand}

    # Stage 2: complete records for those spellings from the live API
    def q(dataset, fields, names):
        out = []
        for i in range(0, len(names), 40):
            chunk = names[i:i+40]
            where = "vendor in (" + ",".join("'" + n.replace("'", "''") + "'" for n in chunk) + ")"
            r = requests.get(f"https://data.sf.gov/resource/{dataset}.json", params={"$select": fields, "$where": where, "$limit": 50000}, timeout=120)
            r.raise_for_status(); out += r.json()
        return pd.DataFrame(out)
    allnames = [n for k in cand for n in spellings[k]]
    vv = q("n9pm-xkyq", "fiscal_year,department,purchase_order,vendor,vouchers_paid,voucher", allnames)
    pp = q("p5r5-fd7g", "purchase_order,purchase_order_date", allnames)
    vv = vv.rename(columns={"fiscal_year":"fy","department":"dept","purchase_order":"po","vouchers_paid":"amount"})
    vv["amount"] = pd.to_numeric(vv["amount"], errors="coerce")
    pp = pp.dropna(subset=["purchase_order_date"]).drop_duplicates("purchase_order").rename(columns={"purchase_order":"po","purchase_order_date":"po_date"})
    pp["po_date"] = pp.po_date.str[:10]
    pp = pp[~pp.po.str.contains("direct payments", case=False)]   # sentinel PO, its date is not a real PO date
    v = vv.merge(pp, on="po", how="left")
    v = v[v.fy.between("2020", "2026") & v.amount.notna()]
    v["key"] = v.vendor.map(canon)
    final = v.groupby("key").agg(n=("amount","size"), npos=("amount", lambda s: (s>0).sum()), fys=("fy","nunique"),
                                 med=("amount", lambda s: s[s>0].median()), spell=("vendor","nunique"))
    final = final[(final.npos>=6)&(final.fys>=2)&(final.n<=250)]
    mk = [k for k in cand if k in final.index and final.loc[k,"spell"]>1][:a.n//3]
    sk = [k for k in cand if k in final.index and final.loc[k,"spell"]==1][:a.n - len(mk)]
    keys = mk + sk
    rng.shuffle(keys)

    vendors = []
    for i, k in enumerate(keys):
        g = v[v.key == k]
        spell = g.vendor.value_counts()
        legal = spell.index[0]
        slug = re.sub(r"[^a-z0-9]+", "-", re.sub(SUFFIX, "", legal.lower())).strip("-")[:28] or f"vendor{i}"
        vid = "V%03d" % (i + 1)
        h = int(hashlib.sha256(vid.encode()).hexdigest(), 16)
        pays = []
        for r in g.sort_values(["po_date","voucher"], na_position="last").itertuples():
            pays.append({"voucher": r.voucher, "po": r.po, "fiscal_year": int(r.fy), "po_date": r.po_date if isinstance(r.po_date, str) else None,
                         "amount": round(float(r.amount), 2), "name_as_paid": r.vendor, "department": r.dept})
        pos_amts = sorted(p["amount"] for p in pays if p["amount"] > 0)
        typical = pos_amts[len(pos_amts)//2]
        vendors.append({
            "vendor_id": vid, "legal_name": legal, "name_variants": list(spell.index),
            "domain": f"{slug}.example",
            "contact_name": f"{FIRST[h%len(FIRST)]} {LAST[(h>>8)%len(LAST)]}",
            "phone": "555-01%02d" % (h % 100) if False else "(415) 555-01%02d" % (h % 100),
            "bank": {"routing": "999%06d" % (h % 10**6), "account": "TEST%07d" % ((h >> 16) % 10**7), "note": "FAKE test values"},
            "typical_amount": typical, "payment_count": len(pays),
            "payments": pays,
            "split": "holdout" if h % 10 < 3 else "dev",   # by vendor, deterministic
            "fabricated_fields": ["domain","contact_name","phone","bank"],
        })
    json.dump(vendors, open(a.out, "w"), indent=1)
    print(len(vendors), "vendors;", sum(len(x["name_variants"])>1 for x in vendors), "with spelling variants;",
          sum(len(x["payments"]) for x in vendors), "payments;", {s: sum(x["split"]==s for x in vendors) for s in ("dev","holdout")})
    print("negatives:", sum(p["amount"]<0 for x in vendors for p in x["payments"]), "zeros:", sum(p["amount"]==0 for x in vendors for p in x["payments"]))
    print("dup voucher+amount rows:", sum(len(x["payments"]) - len({(p["voucher"],p["amount"]) for p in x["payments"]}) for x in vendors))

main()
