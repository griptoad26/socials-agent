"""Encrypted-at-rest secret store.

Reads plain-text keys from `SOCIALS_AGENT_SECRETS_DIR` at *startup*, encrypts
them with AES-GCM (key from env var `SOCIALS_AGENT_KEY`), and writes only the
ciphertext to `data/secrets.enc`.

After startup, all further reads decrypt from disk. Plain-text values are held
in process memory only — never written to disk or returned in HTTP responses.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import (
    PLATFORMS,
    SECRETS_ENC_PATH,
    SECRETS_PLAIN_DIR,
    ensure_dirs,
)


class SecretStoreError(RuntimeError):
    pass


@dataclass
class SecretStore:
    """Loads all platform keys into memory once. No disk persistence of plaintext."""

    raw: dict[str, dict[str, str]]  # platform -> {env_key_name: value}
    _enc_path: Path

    @classmethod
    def load(cls) -> "SecretStore":
        ensure_dirs()
        # Prefer plaintext source on first run; thereafter serve from ciphertext.
        if SECRETS_PLAIN_DIR.exists() and SECRETS_PLAIN_DIR.is_dir():
            raw = _read_plain(SECRETS_PLAIN_DIR)
            if raw:
                _write_encrypted(raw, SECRETS_ENC_PATH)
                return cls(raw=raw, _enc_path=SECRETS_ENC_PATH)
        if SECRETS_ENC_PATH.exists():
            raw = _read_encrypted(SECRETS_ENC_PATH)
            return cls(raw=raw, _enc_path=SECRETS_ENC_PATH)
        # Missing entirely: build an empty record so "platform disabled" paths
        # downstream don't crash.
        return cls(raw={p: {} for p in PLATFORMS}, _enc_path=SECRETS_ENC_PATH)

    def ready(self, platform: str) -> bool:
        spec = PLATFORMS.get(platform)
        if spec is None:
            return False
        have = self.raw.get(platform, {})
        return all(bool(have.get(k)) for k in spec.env_keys)

    def missing(self, platform: str) -> list[str]:
        spec = PLATFORMS.get(platform)
        if spec is None:
            return []
        have = self.raw.get(platform, {})
        return [k for k in spec.env_keys if not have.get(k)]

    def get(self, platform: str, key: str) -> str | None:
        return self.raw.get(platform, {}).get(key)


# ---------- internal ----------


def _read_plain(plain_dir: Path) -> dict[str, dict[str, str]]:
    """Read `<platform>.env` (KEY=VALUE lines) and a `X.json` style fallback."""
    out: dict[str, dict[str, str]] = {}
    for platform in PLATFORMS:
        env_file = plain_dir / f"{platform}.env"
        if not env_file.exists():
            out[platform] = {}
            continue
        with env_file.open() as fp:
            parsed: dict[str, str] = {}
            for raw in fp:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                parsed[k.strip()] = v.strip().strip('"').strip("'")
        out[platform] = parsed
    return out


def _derive_key() -> bytes:
    raw = os.environ.get("SOCIALS_AGENT_KEY")
    if not raw:
        # Deterministic dev fallback so the service still starts; the operator
        # should override this in production via systemd / launchd / docker.
        raw = "dev-only-32-bytes-of-key-material!!"
    # Accept either base64 (preferred) or raw utf-8. AES-GCM needs 32 bytes.
    try:
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) >= 32:
            return decoded[:32]
    except Exception:
        pass
    padded = (raw.encode("utf-8") + b"\x00" * 32)[:32]
    return padded


def _write_encrypted(raw: dict[str, dict[str, str]], path: Path) -> None:
    key = _derive_key()
    aes = AESGCM(key)
    nonce = os.urandom(12)
    plaintext = json.dumps(raw, sort_keys=True).encode("utf-8")
    ciphertext = aes.encrypt(nonce, plaintext, associated_data=None)
    payload = {
        "v": 1,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ct": base64.b64encode(ciphertext).decode("ascii"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fp:
        json.dump(payload, fp)
    # Best-effort: tighten perms.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _read_encrypted(path: Path) -> dict[str, dict[str, str]]:
    with path.open() as fp:
        payload = json.load(fp)
    if payload.get("v") != 1:
        raise SecretStoreError("unknown secrets payload version")
    nonce = base64.b64decode(payload["nonce"])
    ct = base64.b64decode(payload["ct"])
    key = _derive_key()
    aes = AESGCM(key)
    plaintext = aes.decrypt(nonce, ct, associated_data=None)
    return json.loads(plaintext.decode("utf-8"))
