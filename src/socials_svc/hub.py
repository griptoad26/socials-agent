"""Tiny wrapper around the OCMI cluster-hub REST API."""

from __future__ import annotations

from typing import Any

import requests

from .config import HUB_URL


class HubClient:
    def __init__(self, base_url: str = HUB_URL, timeout: int = 5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}{path}",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _patch(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = requests.patch(
            f"{self.base_url}{path}",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def create_task(
        self,
        *,
        title: str,
        category: str = "general",
        description: str = "",
        tags: list[str] | None = None,
        priority: str = "medium",
    ) -> str:
        payload = {
            "title": title,
            "category": category,
            "description": description,
            "tags": tags or [],
            "priority": priority,
        }
        # The hub's POST /api/tasks may vary; fall back to /api/ingest.
        try:
            data = self._post("/api/tasks", payload)
        except Exception:
            data = self._post("/api/ingest", {"kind": "task", **payload})
        return str(data.get("id") or data.get("task_id") or "") or ""

    def append_note(self, task_id: str, note: str) -> None:
        try:
            self._patch(
                f"/api/tasks/{task_id}/notes",
                {"note": note},
            )
        except Exception:
            # The doc says `notes` is also writable via the generic patch.
            self._patch(f"/api/tasks/{task_id}", {"notes": note})

    def update_status(self, task_id: str, status: str) -> None:
        self._patch(f"/api/tasks/{task_id}", {"status": status})

    def log_exec(
        self,
        task_id: str,
        *,
        action: str,
        result: str,
    ) -> None:
        try:
            self._post(
                f"/api/tasks/{task_id}/exec",
                {"action": action, "result": result},
            )
        except Exception:
            pass
