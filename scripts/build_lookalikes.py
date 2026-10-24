"""A3: add real dnstwist permutations of each vendor's fictional .example domain to data/vendors.json.
The fuzzer that produced each lookalike is kept as a feature. TLD swaps use ONLY reserved TLDs (.test/.invalid)
so no real-world domain is ever generated or used."""
import json, random, dnstwist

PREFER = ["homoglyph", "omission", "transposition", "hyphenation", "vowel-swap", "replacement", "addition", "tld-swap", "repetition", "insertion"]

def add_lookalikes(vendors, seed=13):
    rng = random.Random(seed)
    for v in vendors:
        f = dnstwist.Fuzzer(v["domain"], tld_dictionary=["test", "invalid"])
        f.generate()
        perms = [p for p in f.permutations() if p["fuzzer"] != "*original" and p["domain"].isascii() and p["domain"] != v["domain"]]
        by = {}
        for p in perms:
            by.setdefault(p["fuzzer"], []).append(p["domain"])
        picks = []
        for fz in PREFER:
            if fz in by:
                cand = by[fz]
                if fz == "homoglyph":   # keep single-edit, visually close ones
                    cand = [d for d in cand if len(d) == len(v["domain"]) or len(d) == len(v["domain"]) + 1] or cand
                picks.append({"domain": rng.choice(cand), "fuzzer": fz})
        v["lookalikes"] = picks
    return vendors


def main(path="data/vendors.json", seed=13):
    vendors = add_lookalikes(json.load(open(path)), seed)
    json.dump(vendors, open(path, "w"), indent=1)
    from collections import Counter
    print(len(vendors), "vendors;", Counter(p["fuzzer"] for v in vendors for p in v["lookalikes"]))
    print(vendors[0]["domain"], vendors[0]["lookalikes"])

if __name__ == "__main__":
    main()
