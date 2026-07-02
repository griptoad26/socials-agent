#!/usr/bin/env python3
"""
socials-agent reply triage.

Reads data/replies.json, classifies each reply as one of:
    billing | bug | feature | other
using a small keyword bag, and for each billing/bug/feature reply creates a
cluster-hub task via POST http://100.112.11.35:8090/api/tasks.

Title format: "Social: <platform> <user> — <category>"
Description:   "<reply text>\\n\\n— @<handle> on <platform>\\nReceived: <ts>"

Dedupe: each reply id is recorded in data/triaged.json so it isn't re-posted.

Usage:
    python3 src/triage.py             # one-shot
    python3 src/triage.py --loop      # every N seconds
"""

import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ---------- paths ----------
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA_DIR = ROOT / "data"
REPLIES_JSON = DATA_DIR / "replies.json"
TRIAGED_JSON = DATA_DIR / "triaged.json"

HUB_BASE = os.environ.get("CLUSTER_HUB_URL", "http://100.112.11.35:8090")
HUB_ENABLED = os.environ.get("SOCIALS_HUB_ENABLED", "1") == "1"

# ---------- classification ----------
KEYWORDS = {
    "billing": [
        "invoice", "payment", "charge", "refund", "billing",
        "subscription", "pricing", "plan", "receipt",
    ],
    "bug": [
        "bug", "broken", "crash", "error", "fail", "failing", "doesn't work",
        "does not work", "stuck", "wrong", "issue", "traceback",
    ],
    "feature": [
        "feature", "request", "would be nice", "wish", "could you add",
        "cli", "support for", "support ", "integrate", "integration",
        "dry-run", "dry run",
    ],
}

def classify(text: str) -> str:
    """Return the first matching category, or 'other'."""
    t = text.lower()
    for cat, words in KEYWORDS.items():
        for w in words:
            if w in t:
                return cat
    return "other"

# ---------- persistence ----------
def load_replies() -> list:
    if not REPLIES_JSON.exists():
        return []
    try:
        state = json.loads(REPLIES_JSON.read_text())
        return state.get("replies", [])
    except json.JSONDecodeError:
        return []

def load_triaged() -> dict:
    if TRIAGED_JSON.exists():
        try:
            return json.loads(TRIAGED_JSON.read_text())
        except json.JSONDecodeError:
            return {"ids": [], "last_run": None}
    return {"ids": [], "last_run": None}

def save_triaged(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TRIAGED_JSON.write_text(json.dumps(state, indent=2, sort_keys=True))

# ---------- hub client ----------
def _hub_post(path: str, body: dict) -> dict:
    if not HUB_ENABLED:
        return {"id": f"DRYRUN-{int(time.time()*1000)}", "dry_run": True}
    url = f"{HUB_BASE}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        return {"error": str(e), "path": path}

def post_hub_task(title: str, description: str, category: str = "general") -> dict:
    """POST a new task to cluster-hub. Returns the parsed JSON response.

    If SOCIALS_HUB_ENABLED is not "1", we still return a fake success dict so
    downstream code can run without a hub available.
    """
    return _hub_post("/api/tasks", {
        "title": title, "description": description,
        "category": category, "stage": "backlog", "status": "pending",
    })

def log_line(line: str) -> None:
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().astimezone().strftime("%Y-%m-%d")
    log_file = log_dir / f"triage-{ts}.log"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")

# ---------- main ----------
def triage_once(verbose: bool = True) -> dict:
    """Triage all unseen replies. Returns summary."""
    replies = load_replies()
    state = load_triaged()
    seen_ids = set(state["ids"])

    counts = {"billing": 0, "bug": 0, "feature": 0, "other": 0}
    tasks_created = []
    skipped = 0

    for r in replies:
        if r["id"] in seen_ids:
            skipped += 1
            continue
        category = classify(r["text"])
        counts[category] += 1
        seen_ids.add(r["id"])

        if category in ("billing", "bug", "feature"):
            title = f"Social: {r['platform']} {r['handle']} — {category}"
            desc = (
                f"{r['text']}\n\n"
                f"— @{r['handle']} on {r['platform']}\n"
                f"Received: {r['received_at']}\n"
                f"Reply id: {r['id']}"
            )
            resp = post_hub_task(title, desc, category="socials")
            task_id = resp.get("id", "?")
            tasks_created.append({
                "reply_id": r["id"],
                "platform": r["platform"],
                "handle": r["handle"],
                "category": category,
                "task_id": task_id,
            })
            log_line(
                f"{dt.datetime.now().astimezone().isoformat(timespec='seconds')}\t"
                f"{category}\t{r['platform']}\t{r['handle']}\t{task_id}"
            )

    state["ids"] = sorted(seen_ids)
    state["last_run"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    state["counts"] = counts
    state["tasks_created_total"] = state.get("tasks_created_total", 0) + len(tasks_created)
    save_triaged(state)

    if verbose:
        print(
            f"[triage] processed={len(replies) - skipped} new, "
            f"skipped={skipped}, "
            f"billing={counts['billing']} bug={counts['bug']} "
            f"feature={counts['feature']} other={counts['other']}, "
            f"tasks={len(tasks_created)}"
        )
    return {
        "counts": counts,
        "tasks_created": tasks_created,
        "skipped": skipped,
    }

def main() -> None:
    loop = "--loop" in sys.argv
    interval = int(os.environ.get("TRIAGE_INTERVAL", "60"))
    print(f"[start] triage — interval={interval}s loop={loop} hub_enabled={HUB_ENABLED}")
    while True:
        try:
            triage_once()
        except Exception as e:
            print(f"[error] triage failed: {e}", file=sys.stderr)
        if not loop:
            break
        time.sleep(interval)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[stop] interrupted")