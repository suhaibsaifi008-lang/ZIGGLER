"""Long-term memory: facts, preferences, conversation history, reminders.

Flat JSON under evo/data/ per Section 0 — no database in v1.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_PATH = Path(__file__).resolve().parent.parent / "data" / "memory.json"

_MAX_HISTORY = 200


def _load() -> dict[str, Any]:
    if not _PATH.exists():
        return {"facts": {}, "preferences": {}, "history": [], "reminders": []}
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        # Corrupt store: preserve the bad file for recovery instead of losing it.
        import logging
        import shutil

        backup = _PATH.with_suffix(".corrupt")
        shutil.copy2(_PATH, backup)
        logging.getLogger("ziggler.memory").error(
            "memory.json was unreadable (%s); backed up to %s and starting fresh", exc, backup
        )
        data = {}
    for key, default in (("facts", {}), ("preferences", {}), ("history", []), ("reminders", [])):
        data.setdefault(key, default)
    return data
    for key, default in (("facts", {}), ("preferences", {}), ("history", []), ("reminders", [])):
        data.setdefault(key, default)
    return data


def _save(data: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ facts

def remember_fact(key: str, value: str) -> None:
    with _LOCK:
        data = _load()
        data["facts"][key.lower().strip()] = {"value": value, "at": time.time()}
        _save(data)


def recall_fact(key: str) -> str | None:
    with _LOCK:
        entry = _load()["facts"].get(key.lower().strip())
    return entry["value"] if entry else None


def search_facts(query: str) -> dict[str, str]:
    q = query.lower()
    with _LOCK:
        facts = _load()["facts"]
    return {
        k: v["value"]
        for k, v in facts.items()
        if q in k or q in str(v.get("value", "")).lower()
    }


# ------------------------------------------------------------ preferences

def set_preference(key: str, value: str) -> None:
    with _LOCK:
        data = _load()
        data["preferences"][key.lower().strip()] = value
        _save(data)


def get_preference(key: str, default: str = "") -> str:
    with _LOCK:
        return _load()["preferences"].get(key.lower().strip(), default)


# --------------------------------------------------------------- history

def add_message(role: str, content: str) -> None:
    with _LOCK:
        data = _load()
        data["history"].append({"role": role, "content": content[:4000], "ts": time.time()})
        data["history"] = data["history"][-_MAX_HISTORY:]
        _save(data)


def recent_history(limit: int = 12) -> list[dict]:
    with _LOCK:
        history = _load()["history"]
    return [{"role": h["role"], "content": h["content"]} for h in history[-limit:]]


# -------------------------------------------------------------- reminders

def add_reminder(message: str, due_ts: float) -> int:
    with _LOCK:
        data = _load()
        rid = max((r["id"] for r in data["reminders"]), default=0) + 1
        data["reminders"].append({"id": rid, "message": message[:500], "due": due_ts, "done": False})
        _save(data)
        return rid


def due_reminders(now: float | None = None) -> list[dict]:
    now = now if now is not None else time.time()
    with _LOCK:
        data = _load()
        due = [r for r in data["reminders"] if not r["done"] and r["due"] <= now]
        for r in due:
            r["done"] = True
        if due:
            _save(data)
    return due


def pending_reminders() -> list[dict]:
    with _LOCK:
        return [r for r in _load()["reminders"] if not r["done"]]


def cancel_reminder(reminder_id: int) -> bool:
    with _LOCK:
        data = _load()
        before = len(data["reminders"])
        data["reminders"] = [r for r in data["reminders"] if r["id"] != reminder_id]
        removed = len(data["reminders"]) < before
        if removed:
            _save(data)
        return removed


# ----------------------------------------------------------- orchestrator API (Section 2)

def record(entry: dict) -> None:
    kind = entry.get("kind", "fact")
    if kind == "fact":
        remember_fact(entry.get("key", ""), entry.get("value", ""))
    elif kind == "preference":
        set_preference(entry.get("key", ""), entry.get("value", ""))


def recall(query: str) -> list[dict]:
    results: list[dict] = [{"kind": "fact", **{k: v for k, v in f.items()}} for f in []]
    for key, value in search_facts(query).items():
        results.append({"kind": "fact", "key": key, "value": value})
    return results
