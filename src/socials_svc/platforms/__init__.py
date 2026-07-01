"""Platform adapter protocol + import-or-skip wrappers.

Each platform module exposes:
    post(text: str, **kwargs) -> dict
    recent_replies(since: datetime) -> list[dict]

Both methods return a {"ok": bool, "id": str|None, "error": str|None, ...}
dict. If keys are missing or the SDK cannot be imported, they return a
{"ok": False, "error": "...", "skipped": True} payload.
"""

from .base import PlatformAdapter, PostResult, Reply  # noqa: F401
