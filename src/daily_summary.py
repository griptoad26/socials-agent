#!/usr/bin/env python3
"""
socials-agent daily summary.

At 9:00am Pacific each day, post a one-line summary to the cluster-hub as a
task, then mark it complete. Format:

    Title:       "Daily socials summary YYYY-MM-DD"
    Description: "Posts sent: N. Replies received: N. Tasks created: N. Top reply: <text>"

The "top reply" is the longest billing/bug/feature reply from the last 24h
(falling back to the longest of any kind). If there's nothing, the field is
omitted.

Usage:
    python3 src/daily_summary.py            # one-shot (check + post if 9am window)
    python3 src/daily_summary.py --force    # ignore the time window
    python3 src/daily_summary.py --loop     # idle until 9am, then run
"""

import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

# ---------- paths ----------
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA_DIR = ROOT / "data"
POSTED_JSON = DATA_DIR / "posted.json"
REPLIES_JSON = DATA_DIR / "replies.json"
TRIAGED_JSON = DATA_DIR / "triaged.json"

HUB_BASE = os.environ.get("CLUSTER_HUB_URL", "http://100.112.11.35:8090")
HUB_ENABLED = os.environ.get("SOCIALS_HUB_ENABLED", "1") == "1"
PT = ZoneInfo("America/Los_Angeles")

# When in PT does the summary fire?
SUMMARY_HOUR = int(os.environ.get("SUMMARY_HOUR_PT", "9"))
SUMMARY_WINDOW_MIN = 30  # don't double-fire if we tick twice in this window

LAST_RUN_FILE = DATA_DIR / "summary_last_run.json"

# ---------- helpers ----------
def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default

def _within(entry: dict, key: str, since: dt.datetime) -> bool:
    """True if entry[key] is an ISO timestamp >= since."""
    raw = entry.get(key)
    if not raw:
        return False
    try:
        ts = dt.datetime.fromisoformat(raw)
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts >= since

def count_posts_sent(since: dt.datetime) -> int:
    data = _load_json(POSTED_JSON, {})
    return sum(1 for e in (data.values() if isinstance(data, dict) else []) if _within(e, "posted_at", since))

def count_replies(since: dt.datetime) -> int:
    state = _load_json(REPLIES_JSON, {"replies": []})
    return sum(1 for r in state.get("replies", []) if _within(r, "received_at", since))

def tasks_created(_since: dt.datetime) -> int:
    # triaged.json has no per-run timestamps; total since last reset is good enough.
    state = _load_json(TRIAGED_JSON, {"tasks_created_total": 0})
    return state.get("tasks_created_total", 0)

def top_reply(since: dt.datetime) -> str:
    state = _load_json(REPLIES_JSON, {"replies": []})
    candidates = [r for r in state.get("replies", []) if _within(r, "received_at", since)]
    if not candidates:
        return ""
    priority = ("billing", "bug", "feature", "invoice", "refund", "crash", "error", "request")
    best = max(candidates, key=lambda r: (
        1 if any(w in r["text"].lower() for w in priority) else 0,
        len(r["text"]),
    ))
    text = best["text"]
    if len(text) > 140:
        text = text[:137] + "..."
    return f'"{text}" — @{best["handle"]} on {best["platform"]}'

def already_fired_today(now_pt: dt.datetime) -> bool:
    state = _load_json(LAST_RUN_FILE, {})
    last = state.get("last_run_pt_date")
    return last == now_pt.strftime("%Y-%m-%d")

def record_fired(now_pt: dt.datetime, task_id: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(json.dumps(
        {"last_run_pt_date": now_pt.strftime("%Y-%m-%d"), "task_id": task_id},
        indent=2, sort_keys=True,
    ))

# ---------- hub client ----------
def _hub(method: str, path: str, body: dict | None = None) -> dict:
    """Single hub HTTP helper. Returns parsed JSON or {"error": ...}."""
    if not HUB_ENABLED:
        return {"id": f"DRYRUN-{int(time.time()*1000)}", "dry_run": True}
    url = f"{HUB_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        return {"error": str(e), "path": path}

def post_hub_task(title: str, description: str) -> dict:
    return _hub("POST", "/api/tasks", {
        "title": title, "description": description,
        "category": "socials", "stage": "backlog", "status": "pending",
    })

def mark_task_complete(task_id: str) -> dict:
    """Cluster-hub uses PATCH /api/tasks/<id> {"status": "completed"}
    (no /complete subroute)."""
    if not HUB_ENABLED or task_id.startswith("DRYRUN-") or task_id == "?":
        return {"id": task_id, "skipped": True}
    return _hub("PATCH", f"/api/tasks/{task_id}", {"status": "completed"})

def log_line(line: str) -> None:
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().astimezone().strftime("%Y-%m-%d")
    log_file = log_dir / f"daily-summary-{ts}.log"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")

# ---------- main ----------
def post_summary(now_pt: dt.datetime, force: bool = False) -> dict:
    if not force and already_fired_today(now_pt):
        return {"skipped": "already_fired_today"}
    if not force and now_pt.hour != SUMMARY_HOUR:
        return {"skipped": "not_in_window", "now_hour_pt": now_pt.hour}

    since = now_pt - dt.timedelta(days=1)
    posts_n = count_posts_sent(since)
    replies_n = count_replies(since)
    tasks_n = tasks_created(since)
    top = top_reply(since)

    title = f"Daily socials summary {now_pt.strftime('%Y-%m-%d')}"
    parts = [
        f"Posts sent: {posts_n}.",
        f"Replies received: {replies_n}.",
        f"Tasks created: {tasks_n}.",
    ]
    if top:
        parts.append(f"Top reply: {top}")
    description = " ".join(parts)

    resp = post_hub_task(title, description)
    task_id = resp.get("id", "?")
    complete = mark_task_complete(task_id)
    record_fired(now_pt, task_id)

    log_line(
        f"{now_pt.isoformat(timespec='seconds')}\t{task_id}\t"
        f"posts={posts_n} replies={replies_n} tasks={tasks_n}"
    )

    return {"task_id": task_id, "complete": complete, "description": description}

def main() -> None:
    force = "--force" in sys.argv
    loop = "--loop" in sys.argv
    interval = int(os.environ.get("DAILY_SUMMARY_INTERVAL", "300"))
    print(
        f"[start] daily_summary — hour_pt={SUMMARY_HOUR} "
        f"loop={loop} force={force} hub_enabled={HUB_ENABLED}"
    )
    while True:
        now_pt = dt.datetime.now(PT)
        result = post_summary(now_pt, force=force)
        print(f"[summary] {json.dumps(result)[:200]}")
        if not loop:
            break
        time.sleep(interval)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[stop] interrupted")