#!/usr/bin/env python3
"""
socials-agent reply monitor.

Polls X / Mastodon / Bluesky for recent replies + mentions + DMs and persists
them to data/replies.json. The actual HTTP calls are STUBS — they synthesize a
small handful of fake replies so the rest of the pipeline (triage, daily
summary) has something to chew on until real API credentials are wired up.

Swap the stub functions in ``fetch_*`` with real HTTP calls when keys arrive;
the persistence layer and dedupe logic below stay the same.

Usage:
    python3 src/reply_monitor.py            # one-shot poll
    python3 src/reply_monitor.py --loop     # poll every N seconds (default 120)
"""

import datetime as dt
import hashlib
import json
import os
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# ---------- paths ----------
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA_DIR = ROOT / "data"
REPLIES_JSON = DATA_DIR / "replies.json"

HUB_BASE = os.environ.get("CLUSTER_HUB_URL", "http://100.112.11.35:8090")
HUB_ENABLED = os.environ.get("SOCIALS_HUB_ENABLED", "0") == "1"  # default OFF for stubs

# ---------- platform stubs ----------
def fetch_x(since: dt.datetime) -> list:
    """TODO: real X v2 mentions timeline call.
    Needs X_BEARER_TOKEN. Example shape:
        url = "https://api.twitter.com/2/users/me/mentions"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        ...
    """
    # Deterministic-ish stub: emit one or two fake replies per poll.
    seeds = [
        ("ada_lovelace", "x", "your scheduler post was helpful — is there an open API?"),
        ("grace_h", "x", "love this. we have a feature request: a CLI flag for dry-run."),
    ]
    return [_stub_reply(handle, "x", text, since) for handle, _, text in seeds]

def fetch_mastodon(since: dt.datetime) -> list:
    """TODO: real Mastodon notifications call.
    Needs MASTODON_INSTANCE + MASTODON_TOKEN. Example shape:
        url = f"{instance}/api/v1/notifications"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        ...
    """
    seeds = [
        ("mastodon_fan", "mastodon", "hey, the 12:30 post on the helpdesk flow — is the source on github?"),
    ]
    return [_stub_reply(handle, "mastodon", text, since) for handle, _, text in seeds]

def fetch_bluesky(since: dt.datetime) -> list:
    """TODO: real Bluesky notifications call.
    Needs BSKY_HANDLE + BSKY_APP_PASSWORD. Example shape:
        from atproto import Client
        ...
    """
    seeds = [
        ("bsky_user.bsky.social", "bluesky", "found a bug: posting the same entry twice when the daemon restarts."),
        ("happy_bsky", "bluesky", "great reminder. ship it."),
    ]
    return [_stub_reply(handle, "bluesky", text, since) for handle, _, text in seeds]

PLATFORM_FETCHERS = {
    "x": fetch_x,
    "mastodon": fetch_mastodon,
    "bluesky": fetch_bluesky,
}

# ---------- helpers ----------
def _stub_reply(handle: str, platform: str, text: str, since: dt.datetime) -> dict:
    """Synthesize a stable reply record (same handle+text → same id)."""
    ts = dt.datetime.now().astimezone()
    digest = hashlib.sha1(f"{platform}|{handle}|{text}".encode()).hexdigest()[:12]
    return {
        "id": f"{platform}_{digest}",
        "platform": platform,
        "handle": handle,
        "text": text,
        "received_at": ts.isoformat(timespec="seconds"),
        "since": since.isoformat(timespec="seconds"),
        "stub": True,
    }

def load_replies() -> dict:
    if REPLIES_JSON.exists():
        try:
            return json.loads(REPLIES_JSON.read_text())
        except json.JSONDecodeError:
            return {"replies": [], "last_poll": None}
    return {"replies": [], "last_poll": None}

def save_replies(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPLIES_JSON.write_text(json.dumps(state, indent=2, sort_keys=True))

def merge_replies(existing: list, fresh: list) -> tuple:
    """Append only unseen replies (by id). Returns (new_list, added_count)."""
    seen = {r["id"] for r in existing}
    added = [r for r in fresh if r["id"] not in seen]
    return existing + added, len(added)

def log_line(line: str) -> None:
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().astimezone().strftime("%Y-%m-%d")
    log_file = log_dir / f"replies-{ts}.log"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")

# ---------- main poll ----------
def poll_once(verbose: bool = True) -> dict:
    """Run one poll cycle. Returns the updated state dict."""
    state = load_replies()
    since_str = state.get("last_poll")
    if since_str:
        since = dt.datetime.fromisoformat(since_str)
    else:
        since = dt.datetime.now().astimezone() - dt.timedelta(hours=24)

    all_fresh = []
    for platform, fetcher in PLATFORM_FETCHERS.items():
        try:
            got = fetcher(since)
            if verbose:
                print(f"[poll] {platform}: {len(got)} fresh")
            all_fresh.extend(got)
        except Exception as e:
            print(f"[error] {platform} poll failed: {e}", file=sys.stderr)

    merged, added = merge_replies(state["replies"], all_fresh)
    state["replies"] = merged
    state["last_poll"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    save_replies(state)

    if added:
        log_line(
            f"{state['last_poll']}\tadded {added} replies "
            f"(total {len(merged)})"
        )
    if verbose:
        print(f"[poll] total replies stored: {len(merged)} (+{added} new)")
    return state

def main() -> None:
    loop = "--loop" in sys.argv
    interval = int(os.environ.get("REPLY_POLL_INTERVAL", "120"))
    print(f"[start] reply_monitor — interval={interval}s loop={loop}")
    while True:
        try:
            poll_once()
        except Exception as e:
            print(f"[error] poll failed: {e}", file=sys.stderr)
        if not loop:
            break
        time.sleep(interval)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[stop] interrupted")