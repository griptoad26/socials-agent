"""Shared types for platform adapters."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any


@dataclass
class PostResult:
    ok: bool
    post_id: str | None = None
    error: str | None = None
    skipped: bool = False
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out.pop("raw", None)
        if self.raw is not None:
            out["raw"] = self.raw
        return out


@dataclass
class Reply:
    platform: str
    reply_id: str
    author: str
    text: str
    created_at: datetime
    in_reply_to: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "reply_id": self.reply_id,
            "author": self.author,
            "text": self.text,
            "created_at": self.created_at.isoformat(),
            "in_reply_to": self.in_reply_to,
        }


class PlatformAdapter:
    name: str = "base"

    def post(self, text: str) -> PostResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def recent_replies(self, since: datetime) -> list[Reply]:  # pragma: no cover - abstract
        raise NotImplementedError
