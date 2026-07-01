"""Append-only post log. JSONL on disk."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

_LOCK = Lock()


def append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, default=str)
    with _LOCK:
        with path.open("a") as fp:
            fp.write(line + "\n")


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open() as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out
