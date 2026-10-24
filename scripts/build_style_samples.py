"""Extract scrubbed style samples (structure/tone only) from Enron + three phishing corpora -> data/local/style_samples.json.
Emails, phones, URLs are redacted; the generator is also told never to reuse names, and generate_emails.py checks outputs
against every address seen in the samples."""
import argparse, json, mailbox, random, re, tarfile, io, zlib
import pandas as pd

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
PHONE = re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")
URL = re.compile(r"https?://\S+|www\.\S+")
seen_addrs = set()

def scrub(t, limit=1400):
    seen_addrs.update(m.group(0).lower() for m in EMAIL.finditer(t))
    t = EMAIL.sub("<addr>", t); t = PHONE.sub("<phone>", t); t = URL.sub("<url>", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()[:limit]

def enron(path, want, rng):
    out, kw = [], re.compile(r"invoice|payment|wire|account|forward|original message|sent from|thanks|please", re.I)
    try:
        tf = tarfile.open(path, mode="r|gz")
        for m in tf:
            if not m.isfile() or len(out) >= want * 6: continue
            txt = tf.extractfile(m).read().decode("latin-1")
            head, _, body = txt.partition("\n\n")
            if not 150 < len(body) < 2500 or not kw.search(body): continue
            out.append({"source": "enron", "text": scrub(body)})
    except (EOFError, zlib.error, tarfile.ReadError):
        pass   # slice of the archive was downloaded; stream ends mid-file
    rng.shuffle(out); return out[:want]

def nazario(paths, want, rng):
    out = []
    for p in paths:
        for msg in mailbox.mbox(p):
            parts = [msg] if not msg.is_multipart() else list(msg.walk())
            for part in parts:
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True)
                    if body:
                        t = body.decode("utf-8", "ignore")
                        if 150 < len(t) < 3000: out.append({"source": "nazario", "text": scrub(t)}); break
    rng.shuffle(out); return out[:want]

def hf(want, rng):
    out = []
    z = pd.read_csv("data/raw/phish_zefang/Phishing_Email.csv").dropna()
    z = z[z["Email Type"] == "Phishing Email"]
    z = z[z["Email Text"].str.contains(r"urgent|immediately|account|payment|invoice|bank|wire", case=False)]
    out += [{"source": "hf-zefang-liu", "text": scrub(t)} for t in z["Email Text"].sample(want, random_state=1) if 100 < len(t) < 3000]
    r = pd.read_parquet("data/raw/phish_renemel/compiled.parquet"); print("renemel cols:", list(r.columns))
    tc = "text"
    r = r[(r["type"] == "phishing") & r[tc].astype(str).str.contains(r"urgent|immediately|payment|invoice|bank|wire", case=False)]
    r = r[r[tc].str.len().between(100, 3000)]
    out += [{"source": "hf-renemel", "text": scrub(t)} for t in r[tc].astype(str).sample(min(want, len(r)), random_state=2) if 100 < len(t) < 3000]
    return out

ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=120); a = ap.parse_args()
rng = random.Random(13)
s = {"enron": enron("data/raw/enron/part.tar.gz", a.n, rng),
     "phishing": nazario(["data/raw/nazario/phishing-2023", "data/raw/nazario/phishing3.mbox"], a.n, rng) + hf(a.n, rng)}
json.dump(s, open("data/local/style_samples.json", "w"), indent=1)
json.dump(sorted(seen_addrs), open("data/raw/seen_addresses.json", "w"))
print({k: len(v) for k, v in s.items()}, "addresses seen (for leak check):", len(seen_addrs))
