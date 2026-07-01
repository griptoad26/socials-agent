# AGENTS.md - socials-agent

## Role
Cross-platform social media scheduler + reply triage.

Posts to X (Twitter), Mastodon, and Bluesky on a calendar, then routes incoming
replies into the helpdesk flow (helpdesk-svc :8770). If a reply classifies as
billing/bug/feature, creates a cluster-hub task.

## Tasks
- Read `calendar.yaml` (3 posts/day baseline across the three platforms).
- Encrypt API keys at rest using AES-GCM with `SOCIALS_AGENT_KEY`.
- Expose `socials-svc` HTTP API on port **8771**.
- Daily 9am summary push to OCMI cluster-hub (http://100.112.11.35:8090).

## Stack
- **Language:** Python 3.12
- **Framework:** FastAPI + uvicorn
- **Platform SDKs:** tweepy (X v2), Mastodon.py, atproto (Bluesky)
- **Crypto:** cryptography (AES-GCM)
- **Calendar:** croniter

## Current Work
- Build the socials-svc skeleton, calendar, encrypted key store, and platform
  adapters (with graceful "missing keys" degradation).

## Secrets
API keys live in `/home/x2/.openclaw/secrets/<platform>.env`. They are read at
service startup, encrypted with AES-GCM (key from `SOCIALS_AGENT_KEY`), and
written to `data/secrets.enc`. Plain-text keys are never written to disk.
