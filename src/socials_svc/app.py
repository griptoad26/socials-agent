"""socials-svc — FastAPI HTTP API + background scheduler loops."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .calendar_loader import ScheduledPost, load_calendar
from .config import (
    CALENDAR_PATH,
    DAILY_LOG,
    HELPDESK_URL,
    HUB_URL,
    HUB_TASK_ID,
    LOGS_DIR,
    PLATFORMS,
    POSTS_LOG,
    REPLIES_LOG,
    TRIAGE_LOG,
    WORKSPACE,
    ensure_dirs,
)
from .hub import HubClient
from .platforms.base import PostResult, Reply
from .platforms.bluesky import BlueskyAdapter
from .platforms.mastodon import MastodonAdapter
from .platforms.x import XAdapter
from .postlog import append as log_append
from .postlog import read as read_log
from .secrets import SecretStore
from .triage import triage_replies


log = logging.getLogger("socials-svc")
logging.basicConfig(
    level=os.environ.get("SOCIALS_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    filename=str(LOGS_DIR / "service.log"),
)

ensure_dirs()
SECRETS = SecretStore.load()
HUB = HubClient(HUB_URL)

# Calendar (reloaded on `POST /v1/socials/reload`).
CALENDAR: list[ScheduledPost] = load_calendar(CALENDAR_PATH)
# Already-sent fingerprints, to make posting idempotent across restarts.
_SENT_FINGERPRINTS: set[str] = {
    f"{r['platform']}|{r['at']}|{r['text'][:32]}"
    for r in read_log(POSTS_LOG)
    if r.get("ok")
}

ADAPTERS = {
    "x": lambda: XAdapter(SECRETS.raw.get("x", {})),
    "mastodon": lambda: MastodonAdapter(SECRETS.raw.get("mastodon", {})),
    "bluesky": lambda: BlueskyAdapter(SECRETS.raw.get("bluesky", {})),
}

app = FastAPI(title="socials-svc", version="0.1.0")


# -------- models --------


class ManualPostRequest(BaseModel):
    platform: str
    text: str


class ScheduleAddRequest(BaseModel):
    at: str
    platform: str
    text: str


class StatusReport(BaseModel):
    service: str
    hub_url: str
    helpdesk_url: str
    platforms: dict[str, dict]


# -------- routes --------


@app.get("/")
def root():
    return {
        "service": "socials-svc",
        "version": app.version,
        "hub": HUB_URL,
        "helpdesk": HELPDESK_URL,
        "task": HUB_TASK_ID,
        "calendar_posts": len(CALENDAR),
        "endpoints": [
            "GET /v1/socials/queue",
            "POST /v1/socials/post",
            "GET /v1/socials/replies",
            "POST /v1/socials/schedule",
            "POST /v1/socials/reload",
            "GET /v1/socials/platforms",
            "GET /v1/socials/status",
        ],
    }


@app.get("/v1/socials/status", response_model=StatusReport)
def status():
    platforms = {}
    for name in PLATFORMS:
        platforms[name] = {
            "ready": SECRETS.ready(name),
            "missing_keys": SECRETS.missing(name),
        }
    return StatusReport(
        service="socials-svc",
        hub_url=HUB_URL,
        helpdesk_url=HELPDESK_URL,
        platforms=platforms,
    )


@app.get("/v1/socials/platforms")
def platforms():
    return {
        name: {
            "ready": SECRETS.ready(name),
            "missing_keys": SECRETS.missing(name),
        }
        for name in PLATFORMS
    }


@app.get("/v1/socials/queue")
def queue():
    now = datetime.now().astimezone()
    horizon = now + timedelta(hours=24)
    upcoming = [
        p.to_dict() for p in CALENDAR
        if now <= _aware(p.at) <= horizon
    ]
    upcoming.sort(key=lambda p: p["at"])
    return {
        "now": now.isoformat(),
        "horizon_hours": 24,
        "count": len(upcoming),
        "posts": upcoming,
    }


@app.post("/v1/socials/post")
def manual_post(req: ManualPostRequest):
    if req.platform not in PLATFORMS:
        raise HTTPException(400, f"unknown platform: {req.platform}")
    result, plain_text = _publish(req.platform, req.text)
    return {
        "platform": req.platform,
        "text_preview": plain_text[:64] + ("…" if len(plain_text) > 64 else ""),
        "result": result.to_dict(),
    }


@app.get("/v1/socials/replies")
def replies(lookback_hours: int = 24):
    """Return recent replies across all platforms + last triage decisions."""
    since = datetime.utcnow() - timedelta(hours=lookback_hours)
    raw_replies: list[dict] = []
    for name, factory in ADAPTERS.items():
        if not SECRETS.ready(name):
            continue
        try:
            adapter = factory()
            for reply in adapter.recent_replies(since):
                raw_replies.append(reply.to_dict())
        except Exception as exc:
            log.warning("replies fetch failed for %s: %s", name, exc)
    decisions = triage_replies(
        (
            Reply(
                platform=r["platform"],
                reply_id=r["reply_id"],
                author=r["author"],
                text=r["text"],
                created_at=datetime.fromisoformat(r["created_at"]),
                in_reply_to=r.get("in_reply_to"),
            )
            for r in raw_replies
        ),
        HUB,
        lookback_hours=lookback_hours,
    )
    return {
        "lookback_hours": lookback_hours,
        "reply_count": len(raw_replies),
        "replies": raw_replies,
        "triage_count": len(decisions),
        "triage": [d.to_dict() for d in decisions],
    }


@app.post("/v1/socials/schedule")
def schedule_post(req: ScheduleAddRequest):
    if req.platform not in PLATFORMS:
        raise HTTPException(400, f"unknown platform: {req.platform}")
    try:
        when = datetime.fromisoformat(req.at)
    except ValueError as exc:
        raise HTTPException(400, f"invalid ISO timestamp: {exc}") from exc
    sp = ScheduledPost(at=when, platform=req.platform, text=req.text)
    CALENDAR.append(sp)
    CALENDAR.sort(key=lambda p: p.at)
    _append_calendar(req)
    return {
        "added": sp.to_dict(),
        "queue_size": len(CALENDAR),
    }


@app.post("/v1/socials/reload")
def reload_calendar():
    global CALENDAR
    CALENDAR = load_calendar(CALENDAR_PATH)
    return {"reloaded": True, "count": len(CALENDAR)}


# -------- helpers --------


def _append_calendar(req: ScheduleAddRequest) -> None:
    """Append a new entry to calendar.yaml in-place (so it survives restarts)."""
    import yaml  # local import — only here
    if CALENDAR_PATH.exists():
        with CALENDAR_PATH.open() as fp:
            data = yaml.safe_load(fp) or {}
    else:
        data = {"timezone": "America/Los_Angeles"}
    if "posts" not in data:
        data["posts"] = []
    data["posts"].append({
        "at": req.at,
        "platform": req.platform,
        "text": req.text,
    })
    with CALENDAR_PATH.open("w") as fp:
        yaml.safe_dump(data, fp, sort_keys=False, allow_unicode=True)


def _aware(dt: datetime) -> datetime:
    """Treat naive datetimes as UTC for ordering comparisons."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt


def _publish(platform: str, text: str) -> tuple[PostResult, str]:
    if not SECRETS.ready(platform):
        missing = ", ".join(SECRETS.missing(platform)) or "all keys"
        result = PostResult(
            ok=False,
            skipped=True,
            error=f"{platform} disabled — missing: {missing}",
        )
        log_append(
            POSTS_LOG,
            {
                "ts": datetime.utcnow().isoformat(),
                "platform": platform,
                "text": text,
                "ok": False,
                "skipped": True,
                "error": result.error,
            },
        )
        return result, text
    adapter = ADAPTERS[platform]()
    result = adapter.post(text)
    log_append(
        POSTS_LOG,
        {
            "ts": datetime.utcnow().isoformat(),
            "platform": platform,
            "text": text,
            "ok": result.ok,
            "skipped": result.skipped,
            "post_id": result.post_id,
            "error": result.error,
        },
    )
    fingerprint = f"{platform}|{datetime.utcnow().isoformat()}|{text[:32]}"
    if result.ok:
        _SENT_FINGERPRINTS.add(fingerprint)
    return result, text


# -------- background loops --------


async def _scheduler_loop() -> None:
    """Poll the calendar and post anything whose `at` is in the past minute."""
    while True:
        try:
            now = datetime.utcnow()
            for sp in CALENDAR:
                when_utc = sp.at.astimezone(tz=None).replace(tzinfo=None) \
                    if sp.at.tzinfo else sp.at
                fp = f"{sp.platform}|{sp.at.isoformat()}|{sp.text[:32]}"
                if fp in _SENT_FINGERPRINTS:
                    continue
                # Trigger window: [at, at + 5min). Outside window → skip.
                if now < when_utc:
                    continue
                if now - when_utc > timedelta(minutes=5):
                    _SENT_FINGERPRINTS.add(fp)  # marked as "missed"
                    continue
                _publish(sp.platform, sp.text)
        except Exception as exc:  # pragma: no cover - belt and braces
            log.exception("scheduler loop error: %s", exc)
        await asyncio.sleep(30)


async def _daily_summary_loop() -> None:
    """At 09:00 Pacific, summarise the last 24h into the cluster hub."""
    while True:
        try:
            now_pt = datetime.now().astimezone()
            target = now_pt.replace(hour=9, minute=0, second=0, microsecond=0)
            if target <= now_pt:
                target = target + timedelta(days=1)
            wait = (target - now_pt).total_seconds()
            log.info("daily summary scheduled in %.0fs", wait)
            await asyncio.sleep(wait)
            await _post_daily_summary()
        except Exception as exc:  # pragma: no cover
            log.exception("daily summary loop error: %s", exc)
            await asyncio.sleep(60)


async def _post_daily_summary() -> None:
    since = datetime.utcnow() - timedelta(hours=24)
    posts = [r for r in read_log(POSTS_LOG) if r.get("ts", "") >= since.isoformat()]
    replies = read_log(REPLIES_LOG)
    triage = [r for r in read_log(TRIAGE_LOG) if r.get("ts", "") >= since.isoformat()]
    by_platform: dict[str, int] = {}
    sent = 0
    skipped = 0
    for p in posts:
        by_platform.setdefault(p.get("platform", "?"), 0)
        if p.get("ok"):
            sent += 1
            by_platform[p["platform"]] += 1
        else:
            skipped += 1
    summary = {
        "service": "socials-svc",
        "window_hours": 24,
        "posts_total": len(posts),
        "posts_sent": sent,
        "posts_skipped": skipped,
        "posts_by_platform": by_platform,
        "platform_readiness": {
            n: {"ready": SECRETS.ready(n), "missing": SECRETS.missing(n)}
            for n in PLATFORMS
        },
        "replies_total": len(replies),
        "triage_count": len(triage),
        "triage_breakdown": {
            cat: sum(1 for t in triage if t.get("category") == cat)
            for cat in {"billing", "bug", "feature", "chatter"}
        },
    }
    note = (
        f"📣 socials-svc 24h summary\n"
        f"posts: {sent} sent / {skipped} skipped (total {len(posts)})\n"
        f"replies: {len(replies)} | triage: {len(triage)}\n"
        f"platforms ready: "
        f"{', '.join(n for n in PLATFORMS if SECRETS.ready(n)) or 'none'}\n"
        f"disabled: "
        f"{', '.join(n for n in PLATFORMS if not SECRETS.ready(n)) or 'none'}"
    )
    log_append(DAILY_LOG, summary)
    try:
        HUB.append_note(HUB_TASK_ID, note)
        HUB.update_status(HUB_TASK_ID, "in_progress")
        HUB.log_exec(
            HUB_TASK_ID,
            action="daily-summary",
            result=f"sent={sent} skipped={skipped} triage={len(triage)}",
        )
    except Exception as exc:
        log.warning("hub summary push failed: %s", exc)


@app.on_event("startup")
async def _startup() -> None:
    log.info(
        "socials-svc starting | posts=%d | platforms_ready=%s",
        len(CALENDAR),
        [n for n in PLATFORMS if SECRETS.ready(n)],
    )
    # Try to attach to the existing hub task so the operator can see liveness.
    try:
        HUB.update_status(HUB_TASK_ID, "in_progress")
        HUB.log_exec(
            HUB_TASK_ID,
            action="startup",
            result=f"posts_loaded={len(CALENDAR)} "
                   f"platforms_ready="
                   f"{[n for n in PLATFORMS if SECRETS.ready(n)]}",
        )
    except Exception as exc:
        log.warning("hub startup hook failed: %s", exc)
    asyncio.create_task(_scheduler_loop())
    asyncio.create_task(_daily_summary_loop())
