"""Tiered permission system (3-tier design carried over from the Pluton work).

Tiers:
  read_only    — no side-effectful actions
  confirmed    — actions allowed only after an explicit per-goal approval
  autonomous   — local trusted operation (default for CLI/voice on this machine)

Grants persist in evo/data/permissions.json.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

TIERS = ("read_only", "confirmed", "autonomous")

_LOCK = threading.Lock()
_PATH = Path(__file__).resolve().parent.parent / "data" / "permissions.json"

DEFAULT_TIER = "autonomous"


def _load() -> dict:
    if not _PATH.exists():
        return {"default_tier": DEFAULT_TIER, "grants": {}}
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = _PATH.with_suffix(".corrupt")
        _PATH.replace(backup)
        import logging

        logging.getLogger("ziggler.permissions").error(
            "permissions.json unreadable; backed up to %s", backup
        )
        data = {}
    data.setdefault("default_tier", DEFAULT_TIER)
    data.setdefault("grants", {})
    return data


def current_tier() -> str:
    with _LOCK:
        return _load()["default_tier"]


def set_tier(tier: str) -> None:
    if tier not in TIERS:
        raise ValueError(f"unknown tier '{tier}'; use one of {TIERS}")
    with _LOCK:
        data = _load()
        data["default_tier"] = tier
        _PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def check(action_kind: str, tier: str | None = None) -> bool:
    """True when `action_kind` may run under the effective tier."""
    effective = (tier or current_tier()).lower()
    if effective == "read_only":
        allowed = set()
    elif effective == "confirmed":
        allowed = {"browser"}
    else:
        allowed = {"browser", "desktop", "code", "skill"}
    return action_kind in allowed
