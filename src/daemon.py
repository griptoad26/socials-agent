#!/usr/bin/env python3
"""
socials-agent daemon.

Runs the four pipeline stages on independent tick intervals, in a single
process:

    1. scheduler        — every 60s, posts due calendar entries
    2. reply_monitor    — every 120s, fetches new replies
    3. triage           — every 60s, classifies replies + creates hub tasks
    4. daily_summary    — every 300s, posts the 9am PT summary if due

The daemon writes its PID to /tmp/socials-agent.pid (overridable via
SOCIALS_AGENT_PID) so run.sh can stop it.

Run:
    python3 src/daemon.py            # foreground
    python3 src/daemon.py &          # background
    ./run.sh start | stop | status

SIGINT / SIGTERM -> clean shutdown, PID file removed.
"""

import datetime as dt
import os
import signal
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import scheduler                # noqa: E402
import reply_monitor            # noqa: E402
import triage                   # noqa: E402
import daily_summary            # noqa: E402

PID_FILE = Path(os.environ.get("SOCIALS_AGENT_PID", "/tmp/socials-agent.pid"))

# Tunable intervals (seconds)
SCHED_TICK    = int(os.environ.get("DAEMON_SCHED_TICK",    "60"))
REPLY_TICK    = int(os.environ.get("DAEMON_REPLY_TICK",    "120"))
TRIAGE_TICK   = int(os.environ.get("DAEMON_TRIAGE_TICK",   "60"))
SUMMARY_TICK  = int(os.environ.get("DAEMON_SUMMARY_TICK",  "300"))

# ---------- logging ----------
LOG_DIR = HERE.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
DAEMON_LOG = LOG_DIR / "daemon.log"

def log(msg: str) -> None:
    ts = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    line = f"{ts}\t{msg}"
    print(line)
    try:
        with DAEMON_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ---------- shutdown ----------
_stop = False
def _handle_signal(signum, _frame):
    global _stop
    log(f"[signal] received {signum}, shutting down")
    _stop = True

signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

# ---------- main loop ----------
def write_pid() -> None:
    PID_FILE.write_text(str(os.getpid()))

def clear_pid() -> None:
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass

def safe(fn, name: str) -> None:
    try:
        fn()
    except Exception as e:
        log(f"[error] {name}: {e}")

def main() -> None:
    write_pid()
    log(f"[start] socials-agent daemon — pid={os.getpid()}")
    log(
        f"[info] sched={SCHED_TICK}s reply={REPLY_TICK}s "
        f"triage={TRIAGE_TICK}s summary={SUMMARY_TICK}s"
    )

    # Pre-load the calendar once so scheduler.py's first tick is fast.
    try:
        entries = scheduler.load_calendar()
        log(f"[info] calendar loaded: {len(entries)} entries")
    except Exception as e:
        log(f"[warn] calendar load failed: {e}")
        entries = []

    # First-fire all four so we don't wait a full interval before the first run
    safe(lambda: scheduler.post_due_entries(entries, scheduler.load_posted(), dt.datetime.now().astimezone()), "scheduler-initial")
    safe(reply_monitor.poll_once, "reply_monitor-initial")
    safe(triage.triage_once, "triage-initial")

    # PT clock for the summary window
    from zoneinfo import ZoneInfo
    PT = ZoneInfo("America/Los_Angeles")

    last_sched = time.monotonic()
    last_reply = time.monotonic()
    last_triage = time.monotonic()
    last_summary = time.monotonic()

    try:
        while not _stop:
            now_mono = time.monotonic()
            now_pt = dt.datetime.now(PT)

            if now_mono - last_sched >= SCHED_TICK:
                posted = scheduler.load_posted()
                n = scheduler.post_due_entries(entries, posted, dt.datetime.now().astimezone())
                if n:
                    log(f"[sched] posted {n} new entries")
                last_sched = now_mono

            if now_mono - last_reply >= REPLY_TICK:
                safe(reply_monitor.poll_once, "reply_monitor")
                last_reply = now_mono

            if now_mono - last_triage >= TRIAGE_TICK:
                safe(triage.triage_once, "triage")
                last_triage = now_mono

            if now_mono - last_summary >= SUMMARY_TICK:
                # Fire if we're inside the 9am PT window OR forced by env.
                force = os.environ.get("SOCIALS_FORCE_SUMMARY") == "1"
                if force or now_pt.hour == daily_summary.SUMMARY_HOUR:
                    safe(lambda: daily_summary.post_summary(now_pt, force=force), "daily_summary")
                last_summary = now_mono

            time.sleep(1)
    finally:
        clear_pid()
        log("[stop] daemon exited cleanly")

if __name__ == "__main__":
    main()