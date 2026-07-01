"""Configuration loading + paths. No secrets are touched here (see secrets.py)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


WORKSPACE = Path(os.environ.get(
    "SOCIALS_AGENT_HOME",
    "/home/x2/.openclaw/agents/socials-agent",
)).resolve()

SRC_DIR = WORKSPACE / "src"
DATA_DIR = WORKSPACE / "data"
LOGS_DIR = WORKSPACE / "logs"

CALENDAR_PATH = WORKSPACE / "calendar.yaml"
SECRETS_PLAIN_DIR = Path(os.environ.get(
    "SOCIALS_AGENT_SECRETS_DIR",
    "/home/x2/.openclaw/secrets",
))
SECRETS_ENC_PATH = DATA_DIR / "secrets.enc"

POSTS_LOG = DATA_DIR / "posts.jsonl"
REPLIES_LOG = DATA_DIR / "replies.jsonl"
TRIAGE_LOG = DATA_DIR / "triage.jsonl"
DAILY_LOG = DATA_DIR / "daily_summary.jsonl"

HELPDESK_URL = os.environ.get("HELPDESK_URL", "http://localhost:8770")
HUB_URL = os.environ.get("OCMI_HUB_URL", "http://100.112.11.35:8090")
HUB_TASK_ID = os.environ.get(
    "OCMI_HUB_TASK_ID", "TASK-xkg-payments-20260701-157"
)


@dataclass(frozen=True)
class PlatformSpec:
    name: str
    env_keys: tuple[str, ...]
    # Used in /v1/socials/platforms to report readiness


PLATFORMS: dict[str, PlatformSpec] = {
    "x": PlatformSpec(
        name="x",
        env_keys=(
            "X_API_KEY", "X_API_SECRET",
            "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET",
        ),
    ),
    "mastodon": PlatformSpec(
        name="mastodon",
        env_keys=("MASTODON_INSTANCE", "MASTODON_ACCESS_TOKEN"),
    ),
    "bluesky": PlatformSpec(
        name="bluesky",
        env_keys=("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"),
    ),
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
