"""Record real Bright Data SERP responses for the demo companies into data/v2/web_verify_fixtures/<id>.json.
    python scripts/record_web_verify.py                 # live: one search per company, overwrites the fixtures (needs the env vars below)
    python scripts/record_web_verify.py --placeholders  # offline: (re)write PLACEHOLDER fixtures from data/v2/demo_real_vendors.json

Needs BRIGHT_DATA_API_KEY and BRIGHT_DATA_SERP_ZONE. Makes exactly one paid request per company. A company whose request is blocked or
fails keeps its existing fixture. Demo companies only: nothing here touches the seed/eval data."""
import argparse, json, sys, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vouch import demo, web_verify


def record(c, timeout=60.0):
    v = demo.verify_request(c)
    query = f"{v['name']} {v['domain']} phone number"
    url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": query, "hl": "en", "gl": "us", "brd_json": "1"})
    status, body = web_verify._httpx_post(url, timeout)
    if status != 200 or not isinstance(body, dict):
        return None, status
    return {"demo_vendor_id": c["demo_vendor_id"], "placeholder": False, "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "query": query, "http_status": status, "serp": body}, status


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--placeholders", action="store_true"); a = ap.parse_args()
    Path(demo.FIXTURE_DIR).mkdir(parents=True, exist_ok=True)
    if not a.placeholders and not web_verify.is_configured():
        raise SystemExit("BRIGHT_DATA_API_KEY and BRIGHT_DATA_SERP_ZONE are not set; nothing recorded")
    for c in demo.companies():
        if a.placeholders:
            fx, status = demo.placeholder_fixture(c), "placeholder"
        else:
            fx, status = record(c)
        if fx is None:
            print(f"{c['demo_vendor_id']}: HTTP {status}, kept the existing fixture"); continue
        demo.fixture_path(c["demo_vendor_id"]).write_text(json.dumps(fx, indent=1))
        print(f"{c['demo_vendor_id']}: wrote {demo.fixture_path(c['demo_vendor_id'])} ({status})")


if __name__ == "__main__":
    main()
