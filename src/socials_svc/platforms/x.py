"""X (Twitter) v2 adapter. Uses tweepy if available; otherwise no-ops cleanly."""

from __future__ import annotations

from datetime import datetime

from .base import PlatformAdapter, PostResult, Reply


class XAdapter(PlatformAdapter):
    name = "x"

    def __init__(self, secrets: dict[str, str]):
        self._secrets = secrets
        self._client = None
        self._init_error: str | None = None
        try:
            import tweepy  # type: ignore
        except Exception as exc:
            self._init_error = f"tweepy not installed: {exc}"
            return
        try:
            self._client = tweepy.Client(
                consumer_key=secrets.get("X_API_KEY"),
                consumer_secret=secrets.get("X_API_SECRET"),
                access_token=secrets.get("X_ACCESS_TOKEN"),
                access_token_secret=secrets.get("X_ACCESS_TOKEN_SECRET"),
            )
        except Exception as exc:
            self._init_error = f"tweepy init failed: {exc}"

    def post(self, text: str) -> PostResult:
        if not self._client:
            return PostResult(
                ok=False,
                skipped=True,
                error=self._init_error or "x client unavailable",
            )
        try:
            resp = self._client.create_tweet(text=text)
            tweet_id = None
            try:
                tweet_id = str(resp.data["id"])  # type: ignore[index]
            except Exception:
                pass
            return PostResult(ok=True, post_id=tweet_id, raw={"raw": resp.data})
        except Exception as exc:
            return PostResult(ok=False, error=f"x post failed: {exc}")

    def recent_replies(self, since: datetime) -> list[Reply]:
        # Real implementation would use v2 mentions timeline / search; without
        # a sandbox we return an empty list and rely on operator-driven uploads.
        return []
