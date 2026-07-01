"""Bluesky adapter. Uses atproto if available."""

from __future__ import annotations

from datetime import datetime

from .base import PlatformAdapter, PostResult, Reply


class BlueskyAdapter(PlatformAdapter):
    name = "bluesky"

    def __init__(self, secrets: dict[str, str]):
        self._secrets = secrets
        self._client = None
        self._init_error: str | None = None
        try:
            from atproto import Client  # type: ignore
        except Exception as exc:
            self._init_error = f"atproto not installed: {exc}"
            return
        try:
            self._client = Client()
            self._client.login(
                login=secrets.get("BLUESKY_HANDLE", ""),
                password=secrets.get("BLUESKY_APP_PASSWORD", ""),
            )
        except Exception as exc:
            self._init_error = f"bluesky login failed: {exc}"
            self._client = None

    def post(self, text: str) -> PostResult:
        if not self._client:
            return PostResult(
                ok=False,
                skipped=True,
                error=self._init_error or "bluesky client unavailable",
            )
        try:
            resp = self._client.send_post(text)
            uri = getattr(resp, "uri", None)
            return PostResult(ok=True, post_id=uri)
        except Exception as exc:
            return PostResult(ok=False, error=f"bluesky post failed: {exc}")

    def recent_replies(self, since: datetime) -> list[Reply]:
        if not self._client:
            return []
        try:
            notifs = self._client.app.bsky.notification.list_notifications(
                limit=40
            )
        except Exception:
            return []
        out: list[Reply] = []
        for n in getattr(notifs, "notifications", []):
            out.append(
                Reply(
                    platform=self.name,
                    reply_id=str(getattr(n, "cid", "")),
                    author=getattr(n, "author", {}).get("handle", "unknown"),
                    text=getattr(n, "reason", "") or "(notification)",
                    created_at=datetime.fromisoformat(
                        getattr(n, "indexed_at", "")
                        .replace("Z", "+00:00")
                    ),
                )
            )
        return out
