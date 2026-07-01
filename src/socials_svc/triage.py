"""Reply triage: classify a reply → bill/bug/feature/chatter, route.

- Tries helpdesk-svc (localhost:8770) for classification.
- If helpdesk-svc is unreachable, falls back to a tiny rule-based classifier
  (so the service still works in isolation).
- For billing/bug/feature, creates a cluster-hub task via the hub client.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from .config import HELPDESK_URL, HUB_TASK_ID, HUB_URL
from .platforms.base import Reply
from .postlog import append as log_append
from .config import TRIAGE_LOG

BILLING_KEYWORDS = (
    "invoice", "charge", "refund", "billing", "subscription",
    "payment", "card", "pricing", "upgrade", "downgrade",
)
BUG_KEYWORDS = (
    "bug", "broken", "error", "crash", "doesn't work", "does not work",
    "fails", "exception", "stack trace", "regression", "outage",
)
FEATURE_KEYWORDS = (
    "feature request", "could you add", "would be nice", "missing",
    "please add", "support for", "would love", "wish list",
)


@dataclass
class TriageDecision:
    reply_id: str
    platform: str
    category: str  # billing|bug|feature|chatter
    confidence: float
    routed_to: str  # hub|helpdesk|drop
    hub_task_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "reply_id": self.reply_id,
            "platform": self.platform,
            "category": self.category,
            "confidence": self.confidence,
            "routed_to": self.routed_to,
            "hub_task_id": self.hub_task_id,
        }


def classify_local(text: str) -> tuple[str, float]:
    """Tiny rule-based fallback classifier. Returns (category, confidence)."""
    haystack = text.lower()
    if any(k in haystack for k in BILLING_KEYWORDS):
        return "billing", 0.78
    if any(k in haystack for k in BUG_KEYWORDS):
        return "bug", 0.72
    if any(k in haystack for k in FEATURE_KEYWORDS):
        return "feature", 0.65
    return "chatter", 0.5


def classify_with_helpdesk(reply: Reply) -> tuple[str, float]:
    """Try helpdesk-svc. Falls back to local classifier."""
    try:
        import requests  # local import to avoid hard dep at module load
    except Exception:
        return classify_local(reply.text)
    try:
        resp = requests.post(
            f"{HELPDESK_URL}/v1/helpdesk/classify",
            json={
                "platform": reply.platform,
                "reply_id": reply.reply_id,
                "author": reply.author,
                "text": reply.text,
                "created_at": reply.created_at.isoformat(),
            },
            timeout=2.5,
        )
        if resp.status_code // 100 == 2:
            payload = resp.json()
            return payload.get("category", "chatter"), float(
                payload.get("confidence", 0.5)
            )
    except Exception:
        pass
    return classify_local(reply.text)


def maybe_create_hub_task(
    reply: Reply,
    category: str,
    hub_client,
    parent_task_id: str = HUB_TASK_ID,
) -> str | None:
    if category not in {"billing", "bug", "feature"}:
        return None
    title = f"[{category}] from {reply.platform} @{reply.author}"
    description = (
        f"Reply triage routed this to `{category}` "
        f"(confidence enough to spawn a task).\n\n"
        f"Original reply:\n> {reply.text}\n\n"
        f"Reply id: {reply.reply_id}\n"
        f"Parent: {parent_task_id}"
    )
    try:
        return hub_client.create_task(
            title=title,
            category=category,
            description=description,
            tags=["triage", f"from-{reply.platform}"],
        )
    except Exception:
        return None


def triage_replies(
    replies: Iterable[Reply],
    hub_client,
    *,
    lookback_hours: int = 24,
) -> list[TriageDecision]:
    """Classify + route replies. Logs every decision."""
    cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
    decisions: list[TriageDecision] = []
    seen_ids: set[str] = set()
    for reply in replies:
        if reply.created_at < cutoff:
            continue
        if reply.reply_id in seen_ids:
            continue
        seen_ids.add(reply.reply_id)
        category, confidence = classify_with_helpdesk(reply)
        routed = "drop"
        hub_task_id: str | None = None
        if category in {"billing", "bug", "feature"} and confidence >= 0.6:
            hub_task_id = maybe_create_hub_task(
                reply, category, hub_client
            )
            if hub_task_id:
                routed = "hub"
            else:
                routed = "helpdesk"
        decision = TriageDecision(
            reply_id=reply.reply_id,
            platform=reply.platform,
            category=category,
            confidence=confidence,
            routed_to=routed,
            hub_task_id=hub_task_id,
        )
        decisions.append(decision)
        log_append(TRIAGE_LOG, {
            **decision.to_dict(),
            "text": reply.text,
            "author": reply.author,
            "ts": datetime.utcnow().isoformat(),
        })
    return decisions
