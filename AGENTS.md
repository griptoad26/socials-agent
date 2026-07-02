# AGENTS.md - socials-agent

## Role
Cross-platform social media scheduler + reply triage.

Posts to X (Twitter), Mastodon, and Bluesky on a calendar, then routes incoming
replies into the helpdesk flow. If a reply classifies as billing/bug/feature,
creates a cluster-hub task. Posts a daily 9am Pacific summary to the hub.

## Tasks
- Read `calendar.yaml` (3 posts/day baseline across the three platforms).
- Encrypt API keys at rest using AES-GCM with `SOCIALS_AGENT_KEY` (planned).
- Expose `socials-svc` HTTP API on port **8771** (planned).
- Daily 9am PT summary push to OCMI cluster-hub (http://100.112.11.35:8090).

## Stack
- **Language:** Python 3.12, stdlib only (urllib, json, hashlib, zoneinfo)
- **External deps:** PyYAML (already in agent workspace)
- **Platform SDKs:** tweepy / Mastodon.py / atproto — TODO when keys arrive
- **Crypto:** cryptography (AES-GCM) — TODO
- **Calendar:** croniter — TODO when a real cron expression is added

## Scripts (`src/`)

| Script | Purpose | Cadence |
|---|---|---|
| `scheduler.py`    | Reads `calendar.yaml`, posts due entries, persists to `data/posted.json` | 60s |
| `reply_monitor.py`| Polls X / Mastodon / Bluesky for replies (stubbed), writes `data/replies.json` | 120s |
| `triage.py`       | Classifies replies (billing/bug/feature/other), creates hub tasks for the first three | 60s |
| `daily_summary.py`| At 9am PT, posts a one-line summary task to cluster-hub and marks it complete | 300s |
| `daemon.py`       | Runs all four above on independent ticks in a single process | always |

All scripts are stdlib-only (urllib + json + hashlib + zoneinfo) and work
without API keys — the platform calls are stubs that synthesize a small set of
fake replies so the rest of the pipeline can be exercised end-to-end.

## Data Layout

```
data/
  posted.json     — calendar entries that have been posted (key = at|platform)
  replies.json    — every reply seen across all three platforms
  triaged.json    — reply ids already classified, plus task-creation counters
  summary_last_run.json — date of the last daily summary fire
logs/
  posted-YYYY-MM-DD.log      — human log of every calendar post
  replies-YYYY-MM-DD.log     — one line per poll that added new replies
  triage-YYYY-MM-DD.log      — one line per hub task created
  daily-summary-YYYY-MM-DD.log — one line per summary fire
  daemon.log                 — daemon lifecycle + tick output
```

## Run

```bash
# one-shot pipeline tick (poll replies → triage → summary)
./run.sh once

# background daemon
./run.sh start       # writes /tmp/socials-agent.pid
./run.sh status
./run.sh stop        # SIGTERM via PID file
./run.sh restart
./run.sh tail        # tail -f logs/daemon.log
```

PID file: `/tmp/socials-agent.pid` (override with `SOCIALS_AGENT_PID`).

## Env Vars

| Var | Default | Purpose |
|---|---|---|
| `CLUSTER_HUB_URL` | `http://100.112.11.35:8090` | Hub base URL |
| `SOCIALS_HUB_ENABLED` | `1` | Set to `0` to dry-run hub POSTs |
| `REPLY_POLL_INTERVAL` | `120` | reply_monitor poll seconds (when run standalone) |
| `TRIAGE_INTERVAL` | `60` | triage tick seconds (standalone) |
| `DAILY_SUMMARY_INTERVAL` | `300` | summary tick seconds (standalone) |
| `SUMMARY_HOUR_PT` | `9` | hour (Pacific) the daily summary fires |
| `DAEMON_*_TICK` | see daemon.py | per-stage tick intervals inside the daemon |
| `SOCIALS_AGENT_PID` | `/tmp/socials-agent.pid` | PID file location |
| `SOCIALS_FORCE_SUMMARY` | `0` | daemon: bypass the 9am PT window |
| `SOCIALS_AGENT_KEY` | — | (planned) AES-GCM key for encrypted secrets |

## Current Work

Completed in this pass:
- `reply_monitor.py`, `triage.py`, `daily_summary.py`, `daemon.py`
- `run.sh` with start / stop / status / restart / tail / once
- `AGENTS.md` updated to describe the new scripts and data layout

Still outstanding:
- Real platform SDKs (tweepy / Mastodon.py / atproto) — stubs in place
- AES-GCM key encryption for `/home/x2/.openclaw/secrets/<platform>.env`
- `socials-svc` FastAPI on port 8771 (encrypt/decrypt, manual post trigger)
- croniter-driven calendar (currently uses absolute ISO timestamps)

## Secrets
API keys live in `/home/x2/.openclaw/secrets/<platform>.env`. They will be read
at service startup, encrypted with AES-GCM (key from `SOCIALS_AGENT_KEY`), and
written to `data/secrets.enc`. Plain-text keys are never written to disk.