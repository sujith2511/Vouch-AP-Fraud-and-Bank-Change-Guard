"""Code checks applied to every written email (history and cases). Facts are verified with code, never with a second LLM call."""
import re

LEAK = re.compile(r"\b(fraud\w*|scam\w*|suspicio\w*|fake|test|phish\w*|spoof\w*|malicious|attacker|hijack\w*|compromis\w*)\b", re.I)
REAL_COS = re.compile(r"\b(motorola|microsoft|salesforce|oracle|google|amazon|paypal|fedex|ups|apple|wells fargo|chase|bank of america|citibank|hsbc|barclays|deutsche|xerox|verizon|at&t|comcast|dell|ibm|cisco)\b", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL = re.compile(r"https?://[^\s<>\")]+|www\.[^\s<>\")]+", re.I)
RESERVED = (".example", ".test", ".invalid")
URGENT = re.compile(r"\b(urgent\w*|immediately|asap|right away|today|time.sensitive|deadline|without delay|as soon as possible)\b", re.I)


def parse_amounts(text):
    """All plausible money values in text, handling 1,234.56 / 1.234,56 / 1234.56 / 1 234,56."""
    out = set()
    for m in re.finditer(r"(?<![\w.])-?\d{1,3}(?:[,.  ]\d{3})*(?:[.,]\d{2})(?![\d])|(?<![\w.])-?\d+(?:[.,]\d{2})(?!\d)", text):
        s = m.group(0).replace(" ", "").replace(" ", "")
        mm = re.search(r"[.,](\d{2})$", s)
        if mm:
            head = re.sub(r"[.,]", "", s[:mm.start()])
            try: out.add(round(float(f"{head}.{mm.group(1)}"), 2))
            except ValueError: pass
    return out


def norm(s):
    return re.sub(r"[^A-Za-z0-9]", "", str(s)).upper()


def has_token(text, token):
    return norm(token) in norm(text)


def check_text(text, allowed_emails, allow_urgency, must_amounts=(), must_tokens=(), word_range=None, extra_banned=()):
    """Returns list of problems (empty == pass)."""
    bad = []
    if LEAK.search(text): bad.append(f"leak word: {LEAK.search(text).group(0)}")
    if REAL_COS.search(text): bad.append(f"real company name: {REAL_COS.search(text).group(0)}")
    for e in EMAIL.findall(text):
        if e.lower() not in allowed_emails: bad.append(f"unexpected email address {e}")
    for u in URL.findall(text):
        u = u.rstrip(".,;:!?)")
        host = re.sub(r"^(https?://)?(www\.)?", "", u, flags=re.I).split("/")[0].split(":")[0].lower()
        if not host.endswith(RESERVED): bad.append(f"non-reserved url {u}")
    if not allow_urgency and URGENT.search(text): bad.append(f"urgency word without urgency in spec: {URGENT.search(text).group(0)}")
    got = parse_amounts(text)
    for a in must_amounts:
        if a is not None and round(abs(a), 2) not in {round(abs(x), 2) for x in got}: bad.append(f"amount {a} missing")
    for t in must_tokens:
        if t and not has_token(text, t): bad.append(f"missing token {t}")
    for b in extra_banned:
        if b and b.lower() in text.lower(): bad.append(f"banned content {b}")
    if word_range:
        n = len(re.findall(r"\S+", text))
        if not word_range[0] <= n <= word_range[1]: bad.append(f"length {n} words outside {word_range}")
    return bad
