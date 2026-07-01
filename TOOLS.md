# TOOLS.md - Local Notes

## Endpoints

- socials-svc HTTP: `http://localhost:8771`
- helpdesk-svc (triage target): `http://localhost:8770`
- OCMI cluster-hub: `http://100.112.11.35:8090`

## Files

- Calendar: `/home/x2/.openclaw/agents/socials-agent/calendar.yaml`
- Encrypted secrets: `/home/x2/.openclaw/agents/socials-agent/data/secrets.enc`
- Post log: `/home/x2/.openclaw/agents/socials-agent/data/posts.jsonl`
- Reply log: `/home/x2/.openclaw/agents/socials-agent/data/replies.jsonl`
- Triage log: `/home/x2/.openclaw/agents/socials-agent/data/triage.jsonl`

## Run

```
SOCIALS_AGENT_KEY=<32-byte base64 key> \
python3 -m uvicorn socials_svc.app:app --host 0.0.0.0 --port 8771
```
