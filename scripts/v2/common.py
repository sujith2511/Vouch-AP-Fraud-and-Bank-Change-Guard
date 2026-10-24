"""Shared helpers for the v2 dataset build. Everything is seeded: same inputs -> byte-identical outputs."""
import hashlib, json, random
from datetime import date, datetime, timedelta

SEED = 13
ANCHOR = date(2026, 10, 20)          # "data as of": newest simulated payment date
CASE_START = date(2026, 9, 14)       # case emails are sent in [CASE_START, ANCHOR]; vendor email history is before CASE_START
V1 = "data/vendors.json"
V2 = "data/v2/vendors.v2.json"
PAYMENTS = "data/v2/payments.v2.jsonl"
BUYER = {"name": "Northgate Municipal", "ap_addr": "ap@northgate.example", "domain": "northgate.example", "ap_team": "Accounts Payable"}
FREEMAIL = ["webmail.test", "mailbox-free.test", "quickmail.test"]       # reserved TLDs only


def rng_for(*parts, seed=SEED):
    h = hashlib.sha256(("|".join(map(str, parts)) + f"|{seed}").encode()).hexdigest()
    return random.Random(int(h, 16))


def load(path):
    return json.load(open(path))


def dump(obj, path):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=False)


def dump_jsonl(rows, path):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=False) + "\n")


def load_jsonl(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def weighted(rng, pairs):
    """pairs: [(value, weight)]"""
    tot = sum(w for _, w in pairs); x = rng.random() * tot
    for v, w in pairs:
        x -= w
        if x <= 0:
            return v
    return pairs[-1][0]


def fy_bounds(fy):
    """SF fiscal year N runs Jul 1 (N-1) to Jun 30 N."""
    return date(fy - 1, 7, 1), date(fy, 6, 30)


def next_weekday(d):
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def iso(d):
    return d.isoformat() if d else None


def money(x, cur="USD"):
    return f"{x:,.2f}"
