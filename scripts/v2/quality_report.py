"""Dataset quality report -> data/v2/quality_report.json (repetition, diversity, shortcut audit). Cheap, seeded."""
import json, math, re, sys
from collections import Counter
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold, cross_val_predict
from scipy.sparse import hstack, csr_matrix
sys.path.insert(0, str(Path(__file__).parent))
from common import load_jsonl

R = load_jsonl("data/v2/emails.jsonl"); n = len(R)
words = lambda t: re.findall(r"[a-z0-9']+", t.lower())
bodies = [r["body_text"] for r in R]
rep = {}
# ---- repetition: TF-IDF cosine and 5-gram Jaccard over bodies (injection payload and pair partners reported separately)
tf = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True).fit_transform(bodies)
cos = (tf @ tf.T).toarray(); np.fill_diagonal(cos, 0)
grams = [set(zip(*[words(b)[i:] for i in range(5)])) for b in bodies]
def jac(a, b): return len(a & b) / max(1, len(a | b))
iu = np.triu_indices(n, 1)
cv = cos[iu]; jv = np.array([jac(grams[i], grams[j]) for i, j in zip(*iu)])
pct = lambda a: {f"p{p}": round(float(np.percentile(a, p)), 3) for p in (50, 90, 99, 99.9)} | {"max": round(float(a.max()), 3)}
pair_ids = {(R[i]["id"], R[j]["id"]) for i in range(n) for j in range(n) if R[i]["truth"]["pair_with"] == R[j]["id"]}
def top(a, k=8):
    idx = np.argsort(-a)[:k]; return [(R[iu[0][x]]["id"], R[iu[1][x]]["id"], round(float(a[x]), 3)) for x in idx]
rep["cosine"] = pct(cv); rep["jaccard5"] = pct(jv)
rep["pairs_cos_gt_0.6"] = int((cv > 0.6).sum()); rep["pairs_cos_gt_0.8"] = int((cv > 0.8).sum()); rep["pairs_jaccard_gt_0.2"] = int((jv > 0.2).sum()); rep["pairs_jaccard_gt_0.4"] = int((jv > 0.4).sum())
rep["top_cosine_pairs"] = top(cv); rep["top_jaccard_pairs"] = top(jv)
def lines(b): return [l.strip() for l in b.split("\n") if l.strip()]
first = Counter(re.sub(r"[^a-z ]", "", lines(b)[0].lower())[:40] for b in bodies if lines(b))
last = Counter(" | ".join(lines(b)[-2:]).lower()[:60] for b in bodies if lines(b))
rep["most_common_openings"] = first.most_common(6); rep["most_common_endings"] = last.most_common(6)
rep["distinct_openings"] = len(first); rep["distinct_endings"] = len(last)
# ---- diversity
ent = lambda c: round(-sum(v / sum(c.values()) * math.log2(v / sum(c.values())) for v in c.values()), 2)
div = {}
for dim, f in {"scenario": lambda r: r["truth"]["scenario"], "channel": lambda r: r["attributes"]["scenario_independent"]["channel"], "thread": lambda r: r["attributes"]["scenario_independent"]["thread"],
               "register": lambda r: r["attributes"]["scenario_independent"]["register"], "length": lambda r: r["attributes"]["scenario_independent"]["length"], "language": lambda r: r["language"],
               "device_footer": lambda r: r["device_footer"], "attachments": lambda r: "+".join(a["type"] for a in r["attachments"]) or "none"}.items():
    c = Counter(f(r) for r in R); div[dim] = {"counts": dict(c), "entropy_bits": ent(c)}
vocab = Counter(w for b in bodies for w in words(b)); L = np.array([len(words(b)) for b in bodies])
div["vocab_size"] = len(vocab); div["body_words"] = {"min": int(L.min()), "median": int(np.median(L)), "p90": int(np.percentile(L, 90)), "max": int(L.max())}
div["thread_structures"] = len({(r["attributes"]["scenario_independent"]["thread"], bool(r["quoted_history"]), len(r["cc"]) > 0) for r in R})
# ---- shortcut audit (vendor-grouped CV)
def feats_artifact(r):
    a = r["attributes"]["scenario_independent"]
    return [len(words(r["body_text"])), r["body_text"].count("\n"), bool(r["quoted_history"]), len(r["attachments"]), len(a["noise"]), a["sent_hour_local"], ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].index(a["sent_local_weekday"]),
            r["language"] != "en", r["device_footer"] != "none", len(r["cc"]), r["body_html_present"], a["urgency"] != "none"]
def feats_header(r):
    h = r["headers"]; v = r["vendor_snapshot"]; inv = r["invoice"]; dom = v.get("domain")
    return [h["spf"] == "pass", h["dkim"] == "pass", h["dmarc"] == "pass", r["sender_domain"] == dom, r["reply_to"].split("@")[1] == r["from_addr"].split("@")[1], min(r["sender_domain_age_days"], 5000) / 5000,
            r["claim_changes_bank"], (inv["amount"] / v["typical_amount"]) if v.get("typical_amount") else 9, h["mailer"] == v.get("usual_mailer"), h["origin_ip"] == v.get("usual_mail_ip"), v.get("in_vendor_master") is True]
y = {"label": np.array([r["truth"]["label"] == "fraud" for r in R]), "lane": np.array([r["truth"]["expected_lane"] for r in R])}
groups = np.array([r["vendor_id"] for r in R]); cvk = GroupKFold(n_splits=5)
A = csr_matrix(np.array([feats_artifact(r) for r in R], float)); H = csr_matrix(np.array([feats_header(r) for r in R], float))
T = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, max_features=4000).fit_transform([r["subject"] + " " + r["body_text"] for r in R])
def acc(X, t):
    from sklearn.preprocessing import MaxAbsScaler
    p = cross_val_predict(LogisticRegression(max_iter=2000, C=1.0), MaxAbsScaler().fit_transform(X), t, cv=cvk, groups=groups); return round(float((p == t).mean()), 3)
audit = {"majority_baseline": {k: round(float(max(Counter(v).values()) / n), 3) for k, v in y.items()}}
for name, X in {"artifact_only (length, lines, quoting, attachments, noise, hour, weekday, language, footer, cc, html, urgency)": A, "body_text_tfidf_only": T, "header_and_fact_features (REAL tells)": H, "text+header": hstack([T, H]).tocsr()}.items():
    audit[name] = {k: acc(X, v) for k, v in y.items()}
hard = np.array([r["truth"]["difficulty"] == "hard" for r in R]); 
from sklearn.preprocessing import MaxAbsScaler
Xall = MaxAbsScaler().fit_transform(hstack([T, H]).tocsr()); p = cross_val_predict(LogisticRegression(max_iter=2000), Xall, y["label"], cv=cvk, groups=groups)
audit["text+header on HARD cases only (label)"] = round(float((p[hard] == y["label"][hard]).mean()), 3)
audit["text+header on EASY/MEDIUM cases only (label)"] = round(float((p[~hard] == y["label"][~hard]).mean()), 3)
out = {"n": n, "repetition": rep, "diversity": div, "shortcut_audit": audit}
json.dump(out, open("data/v2/quality_report.json", "w"), indent=1, default=str)
print(json.dumps({"repetition": {k: v for k, v in rep.items() if k not in ("most_common_openings", "most_common_endings")}, "shortcut_audit": audit, "vocab": div["vocab_size"], "words": div["body_words"], "thread_structures": div["thread_structures"]}, indent=1, default=str))
print("openings:", rep["most_common_openings"]); print("endings:", rep["most_common_endings"])
