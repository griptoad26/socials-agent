"""Mastodon adapter. Uses Mastodon.py if available."""

from __future__ import annotations

from datetime import datetime

from .base import PlatformAdapter, PostResult, Reply


class MastodonAdapter(PlatformAdapter):
    name = "mastodon"

    def __init__(self, secrets: dict[str, str]):
        self._secrets = secrets
        self._client = None
        self._init_error: str | None = None
        try:
            from mastodon import Mastodon  # type: ignore
        except Exception as exc:
            self._init_error = f"mastodon-py not installed: {exc}"
            return
        try:
            instance = secrets.get("MASTODON_INSTANCE", "").rstrip("/")
            if not instance:
                self._init_error = "MASTODON_INSTANCE missing"
                return
            self._client = Mastodon(
                access_token=secrets.get("MASTODON_ACCESS_TOKEN", ""),
                api_base_url=instance,
            )
        except Exception as exc:
            self._init_error = f"mastodon init failed: {exc}"

    def post(self, text: str) -> PostResult:
        if not self._client:
            return PostResult(
                ok=False,
                skipped=True,
                error=self._init_error or "mastodon client unavailable",
            )
        try:
            status = self._client.status_post(text)
            sid = str(getattr(status, "id", "")) or None
            return PostResult(ok=True, post_id=sid)
        except Exception as exc:
            return PostResult(ok=False, error=f"mastodon post failed: {exc}")

    def recent_replies(self, since: datetime) -> list[Reply]:
        if not self._client:
            return []
        try:
            notifs = self._client.notifications(since_id=None, limit=40)
        except Exception:
            return []
        out: list[Reply] = []
        for n in notifs:
            if getattr(n, "type", "") != "mention":
                continue
            acc = getattr(n, "account", None)
            status = getattr(n, "status", None)
            if not status:
                continue
            out.append(
                Reply(
                    platform=self.name,
                    reply_id=str(getattr(status, "id", "")),
                    author=getattr(acc, "acct", "unknown"),
                    text=getattr(status, "content", ""),
                    created_at=getattr(status, "created_at", datetime.utcnow()),
                    in_reply_to=str(getattr(status, "in_reply_to_id", "")) or None,
                )
            )
        return out
