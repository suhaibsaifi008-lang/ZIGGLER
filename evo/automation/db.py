"""Flat-file settings store backing automation/browser_agent.py's `from . import db` contract.

Section 0 locks v1 storage to flat JSON under evo/data/ (no database). The original
EVO/core/db.py was SQLite + config-chain and is intentionally NOT carried over; only the
get_setting/set_setting surface browser_agent actually uses lives here.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_SETTINGS_PATH = _DATA_DIR / "settings.json"


def _read() -> dict[str, Any]:
    if not _SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(data: dict[str, Any]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_setting(key: str, default: str = "") -> str:
    with _LOCK:
        value = _read().get(key, default)
    return str(value)


def set_setting(key: str, value: str) -> None:
    with _LOCK:
        data = _read()
        data[key] = str(value)
        _write(data)
