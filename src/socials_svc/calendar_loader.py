"""Calendar loader. YAML → list of ScheduledPost."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml


@dataclass
class ScheduledPost:
    at: datetime
    platform: str
    text: str

    def to_dict(self) -> dict:
        return {
            "at": self.at.isoformat(),
            "platform": self.platform,
            "text": self.text,
        }


def load_calendar(path: Path) -> list[ScheduledPost]:
    if not path.exists():
        return []
    with path.open() as fp:
        data = yaml.safe_load(fp) or {}
    posts_raw = data.get("posts") or data or []
    out: list[ScheduledPost] = []
    if isinstance(posts_raw, dict):
        posts_raw = list(posts_raw.values())
    for entry in posts_raw:
        platform = entry["platform"]
        at = _parse_iso(entry["at"])
        text = entry["text"]
        out.append(ScheduledPost(at=at, platform=platform, text=text))
    out.sort(key=lambda p: p.at)
    return out


def _parse_iso(value: str) -> datetime:
    # fromisoformat in 3.11+ accepts offsets directly.
    return datetime.fromisoformat(value)
