"""Print distribution tables for data/v2/case_specs.json and enforce the spec-stage gates (non-zero exit on failure)."""
import json, math, sys
from collections import Counter, defaultdict
S = json.load(open("data/v2/case_specs.json")); V = {v["vendor_id"]: v for v in json.load(open("data/v2/vendors.v2.json"))}
fails = []

def ent(c):
    t = sum(c.values()); return -sum(n / t * math.log2(n / t) for n in c.values() if n)

def table(title, c, total=None):
    total = total or sum(c.values()); e = ent(c)
    print(f"\n{title} (entropy {e:.2f} bits)"); [print(f"  {str(k):<46}{n:>4}  {100*n/total:5.1f}%") for k, n in sorted(c.items(), key=lambda kv: (-kv[1], str(kv[0])))]

n = len(S); print(f"{n} case specs")
table("scenario", Counter(s["scenario"] for s in S)); table("family", Counter(s["family"] for s in S))
table("label", Counter(s["label"] for s in S)); table("difficulty", Counter(s["difficulty"] for s in S)); table("split (by vendor)", Counter(s["split"] for s in S))
table("expected_lane", Counter(s["lane"] for s in S)); table("correct_agent_verdict", Counter(s["verdict"] for s in S))
for dim in ("channel", "thread", "length", "register", "device_footer", "language", "urgency", "sent_local_weekday"):
    table(dim, Counter(s["attrs"][dim] for s in S))
table("noise features", Counter(x for s in S for x in s["attrs"]["noise"]) or Counter({"(none)": 0}))
table("attachments", Counter("+".join(a["type"] for a in s["attachments"]) or "none" for s in S))
table("sent hour bucket", Counter("night(0-5,22-23)" if (s["attrs"]["sent_hour_local"] < 6 or s["attrs"]["sent_hour_local"] >= 22) else "business(8-16)" if 8 <= s["attrs"]["sent_hour_local"] <= 16 else "shoulder" for s in S))
table("lookalike fuzzer", Counter(s["lookalike_fuzzer"] for s in S if s["lookalike_fuzzer"]))
table("injection placement", Counter(s["injection"]["hidden_in"] for s in S if s["injection"])); table("injection style", Counter(s["injection"]["style"] for s in S if s["injection"]))
table("tells (id)", Counter(t["id"] for s in S for t in s["tells"]))
table("surface features (legit)", Counter(f for s in S for f in s["surface_features"] if s["label"] == "legit"))
table("vendor country", Counter(V[s["vendor_id"]]["country"] for s in S)); uses = Counter(s["vendor_id"] for s in S)
print(f"\nvendors used: {len(uses)} (max {max(uses.values())} cases/vendor, min {min(uses.values())})")
print("\nscenario x split:")
by = defaultdict(Counter)
for s in S: by[s["scenario"]][s["split"]] += 1
for k, c in by.items(): print(f"  {k:<44} dev {c['dev']:>2}  holdout {c['holdout']:>2}")

# ------------- gates
for k, c in by.items():
    if sum(c.values()) < 8: fails.append(f"scenario {k} has only {sum(c.values())} cases")
    if c["dev"] < 2 or c["holdout"] < 2: fails.append(f"scenario {k} missing from a split: {dict(c)}")
hard = sum(s["difficulty"] == "hard" for s in S) / n; print(f"\nhard share {hard:.1%}")
if hard < 0.35: fails.append(f"hard share {hard:.1%} < 35%")
vec = Counter((s["scenario"], s["difficulty"], s["attrs"]["channel"], s["attrs"]["thread"], s["attrs"]["length"], s["attrs"]["register"], s["attrs"]["device_footer"], s["attrs"]["language"],
               tuple(a["type"] for a in s["attachments"]), s["attrs"]["urgency"], tuple(s["attrs"]["noise"]), s["sub_variant"]) for s in S)
rep = [k for k, c in vec.items() if c > 1]
if rep: fails.append(f"{len(rep)} repeated attribute vectors")
vs = {}
for s in S:
    if V[s["vendor_id"]]["split"] != s["split"]: fails.append(f"{s['id']} split != vendor split")
    if s["label"] == "legit" and s["lane"] == "auto_clear" and s["claim_changes_bank"]: fails.append(f"{s['id']} auto_clear with bank change")
    if s["label"] == "fraud" and s["lane"] == "auto_clear": fails.append(f"{s['id']} fraud expected auto_clear")
    if s["family"] == "legit" and s["difficulty"] == "hard" and not s["surface_features"]: fails.append(f"{s['id']} hard legit without fraud-looking surface features ({s['scenario']})")
    if s["family"] != "legit" and s["difficulty"] == "hard" and not s["tells"] and False: pass
    if s["label"] == "fraud" and not s["tells"]: fails.append(f"{s['id']} fraud with no tells")
for sid in {s["pair_id"] for s in S if s.get("pair_id")}:
    p = [s for s in S if s.get("pair_id") == sid]
    if len(p) != 2 or p[0]["vendor_id"] != p[1]["vendor_id"] or p[0]["split"] != p[1]["split"]: fails.append(f"pair {sid} inconsistent")
print("\nGATE FAILURES:" if fails else "\nspec gates: ALL PASS"); [print("  -", f) for f in fails[:40]]; print(f"({len(fails)} total)" if fails else "")
sys.exit(1 if fails else 0)
