#!/usr/bin/env python3
"""
socials-agent scheduler.

Loads calendar.yaml, and once per minute posts any due entries that haven't
been posted yet. "Posting" for now is a stub: it logs to logs/posted-YYYY-MM-DD.log
and appends to data/posted.json. Real X / Mastodon / Bluesky API calls are
stubbed with TODOs so the user can drop in API keys later.

Usage:
    python3 src/scheduler.py

Run in the background with nohup:
    nohup python3 src/scheduler.py > logs/scheduler.out 2>&1 &

Stop with: pkill -f src/scheduler.py
"""

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import yaml  # PyYAML is in the stdlib-adjacent set; already used by the agent workspace

# ---------- paths ----------
HERE = Path(__file__).resolve().parent            # .../src
ROOT = HERE.parent                                  # agent workspace root
CALENDAR_PATH = ROOT / "calendar.yaml"
LOG_DIR = ROOT / "logs"
DATA_DIR = ROOT / "data"
POSTED_JSON = DATA_DIR / "posted.json"

# ---------- platform stubs ----------
def post_to_x(text: str, at: dt.datetime) -> None:
    """TODO: real X (Twitter) v2 API call. Needs API key + bearer token."""
    # Example shape:
    #   import tweepy
    #   client = tweepy.Client(bearer_token=os.environ["X_BEARER_TOKEN"])
    #   client.create_tweet(text=text)
    print(f"[STUB] would post to X at {at.isoformat()}: {text[:60]}...")

def post_to_mastodon(text: str, at: dt.datetime) -> None:
    """TODO: real Mastodon API call. Needs instance URL + access token."""
    # Example shape:
    #   import requests
    #   requests.post(f"{instance}/api/v1/statuses",
    #                 data={"status": text},
    #                 headers={"Authorization": f"Bearer {token}"})
    print(f"[STUB] would post to Mastodon at {at.isoformat()}: {text[:60]}...")

def post_to_bluesky(text: str, at: dt.datetime) -> None:
    """TODO: real Bluesky API call. Needs handle + app password."""
    # Example shape:
    #   from atproto import Client
    #   client = Client()
    #   client.login(os.environ["BSKY_HANDLE"], os.environ["BSKY_APP_PASSWORD"])
    #   client.send_post(text=text)
    print(f"[STUB] would post to Bluesky at {at.isoformat()}: {text[:60]}...")

PLATFORM_DISPATCH = {
    "x": post_to_x,
    "mastodon": post_to_mastodon,
    "bluesky": post_to_bluesky,
}

# ---------- persistence ----------
def load_posted() -> dict:
    if POSTED_JSON.exists():
        try:
            return json.loads(POSTED_JSON.read_text())
        except json.JSONDecodeError:
            return {}
    return {}

def save_posted(posted: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    POSTED_JSON.write_text(json.dumps(posted, indent=2, sort_keys=True))

def log_posted(entry: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    now_pt = dt.datetime.now().astimezone()
    log_file = LOG_DIR / f"posted-{now_pt.strftime('%Y-%m-%d')}.log"
    ts = now_pt.isoformat(timespec="seconds")
    line = (
        f"{ts}\t{entry['at']}\t{entry['platform']}\t"
        f"{entry['key']}\t{entry['text']}\n"
    )
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line)

# ---------- calendar handling ----------
def entry_key(entry: dict) -> str:
    """Stable identifier for an entry — used as the dedupe key in posted.json."""
    return f"{entry['at']}|{entry['platform']}"

def load_calendar() -> list:
    """Load and parse calendar.yaml.

    Tolerates a top-level scalar key like `timezone: America/Los_Angeles` by
    stripping lines that look like top-level key/value pairs before handing the
    remainder to PyYAML as a list-of-posts document.
    """
    if not CALENDAR_PATH.exists():
        print(f"[warn] calendar not found at {CALENDAR_PATH}", file=sys.stderr)
        return []

    text = CALENDAR_PATH.read_text()
    list_only_lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        # Drop top-level scalar keys (no leading '-', not part of a list item)
        if (
            stripped
            and not stripped.startswith("#")
            and not stripped.startswith("- ")
            and not stripped.startswith("-")
            and ":" in stripped
            and not line.startswith((" ", "\t"))
        ):
            continue
        list_only_lines.append(line)

    list_doc = "\n".join(list_only_lines)
    try:
        raw = yaml.safe_load(list_doc)
    except yaml.YAMLError as e:
        print(f"[error] calendar YAML parse failed: {e}", file=sys.stderr)
        return []

    if isinstance(raw, list):
        return [e for e in raw if isinstance(e, dict)]
    if isinstance(raw, dict):
        return [v for v in raw.values() if isinstance(v, dict) and "at" in v]
    return []  # empty calendar

def render_text(entry: dict, now: dt.datetime) -> str:
    """Light templating: {date} and {weekday} get expanded if present."""
    text = entry.get("text", "")
    weekday = now.strftime("%A")
    date = now.strftime("%Y-%m-%d")
    return text.replace("{date}", date).replace("{weekday}", weekday)

def parse_at(entry: dict) -> dt.datetime:
    """Parse `at` (ISO 8601 with offset) into an aware datetime.

    Accepts a string ('2026-07-01T09:00:00-07:00') or a datetime already produced
    by PyYAML's timestamp parsing. Result is always timezone-aware; naive
    datetimes are assumed to be in the calendar's declared timezone (or UTC).
    """
    raw_at = entry["at"]
    if isinstance(raw_at, dt.datetime):
        at = raw_at
    else:
        at = dt.datetime.fromisoformat(str(raw_at))

    if at.tzinfo is None:
        # Calendar entries are Pacific Time per the file's `timezone:` line
        tz_name = entry.get("timezone") or "America/Los_Angeles"
        try:
            from zoneinfo import ZoneInfo
            at = at.replace(tzinfo=ZoneInfo(tz_name))
        except Exception:
            at = at.replace(tzinfo=dt.timezone.utc)
    return at

def post_due_entries(entries: list, posted: dict, now: dt.datetime) -> int:
    """Post any entries with at <= now that haven't been posted. Return count posted."""
    count = 0
    for entry in entries:
        key = entry_key(entry)
        if key in posted:
            continue
        try:
            at = parse_at(entry)
        except (KeyError, ValueError) as e:
            print(f"[warn] skipping entry with bad 'at': {e}", file=sys.stderr)
            continue
        if at > now:
            continue

        # Resolve platform — call stub
        platform = entry.get("platform", "").lower()
        dispatcher = PLATFORM_DISPATCH.get(platform)
        if dispatcher is None:
            print(f"[warn] unknown platform '{platform}', skipping", file=sys.stderr)
            continue

        text = render_text(entry, now)
        try:
            dispatcher(text, at)
        except Exception as e:
            print(f"[error] post failed for {key}: {e}", file=sys.stderr)
            continue

        entry_record = {
            "key": key,
            "at": at.isoformat(),  # always serialize as ISO string
            "platform": platform,
            "text": text,
            "posted_at": now.isoformat(timespec="seconds"),
        }
        posted[key] = entry_record
        log_posted(entry_record)
        count += 1
        print(f"[ok] posted {key}")

    if count:
        save_posted(posted)
    return count

# ---------- main loop ----------
def main() -> None:
    print(f"[start] socials-agent scheduler — {dt.datetime.now().isoformat(timespec='seconds')}")
    print(f"[info] calendar: {CALENDAR_PATH}")
    print(f"[info] log dir : {LOG_DIR}")
    print(f"[info] posted  : {POSTED_JSON}")

    entries = load_calendar()
    print(f"[info] loaded {len(entries)} calendar entries")

    # First tick — process anything already due (handy for backfills / tests)
    now = dt.datetime.now().astimezone()
    posted = load_posted()
    n = post_due_entries(entries, posted, now)
    print(f"[tick 0] posted {n} new entries")

    # Loop once per minute
    while True:
        time.sleep(60)
        now = dt.datetime.now().astimezone()
        posted = load_posted()
        n = post_due_entries(entries, posted, now)
        print(f"[tick {now.strftime('%H:%M')}] posted {n} new entries")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[stop] interrupted")
