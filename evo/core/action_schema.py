"""Dataclasses for every action any agent performs (Section 4).

Every verify() here re-checks real system state via the owning agent — never a
stub returning True. A missing or empty expectation raises instead of passing.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class Action:
    kind: Literal["browser", "desktop", "code", "skill"]
    description: str
    payload: dict = field(default_factory=dict)

    def execute(self) -> dict:
        """Perform the action via its agent and return the raw result object."""
        if self.kind == "browser":
            return _execute_browser(self.payload)
        if self.kind == "desktop":
            return _execute_desktop(self.payload)
        if self.kind == "code":
            return _execute_code(self.payload)
        if self.kind == "skill":
            return _execute_skill(self.payload)
        raise ValueError(f"unknown action kind '{self.kind}'")

    def verify(self) -> bool:
        """Re-check postcondition against live system state."""
        if self.kind == "browser":
            return _verify_browser(self.payload)
        if self.kind == "desktop":
            return _verify_desktop(self.payload)
        if self.kind == "code":
            return _verify_code(self.payload)
        if self.kind == "skill":
            return _verify_skill(self.payload)
        raise ValueError(f"unknown action kind '{self.kind}'")


@dataclass
class GoalResult:
    success: bool
    completed_steps: list[Action] = field(default_factory=list)
    failure_reason: str | None = None
    plan: list[Action] = field(default_factory=list)


# --------------------------------------------------------------------------
# browser (delegates to evo.automation.browser_agent — moved unchanged)
# --------------------------------------------------------------------------

def _require_expect(payload: dict) -> dict:
    expect = payload.get("expect") or {}
    if not expect.get("kind"):
        raise ValueError("payload['expect'] must define {'kind': ..., 'value': ...}")
    return expect


def _execute_browser(payload: dict) -> dict:
    from evo.automation import browser_agent

    op = payload.get("op")
    if op == "navigate":
        return browser_agent.navigate(payload["url"])
    if op == "click":
        return browser_agent.click(payload["desc"])
    if op == "fill":
        return browser_agent.fill(payload["desc"], payload["text"], submit=payload.get("submit", False))
    if op == "read":
        return browser_agent.read(max_chars=payload.get("max_chars", 2600))
    raise ValueError(f"unknown browser op '{op}'")


def _verify_browser(payload: dict) -> bool:
    from evo.automation import browser_agent

    expect = _require_expect(payload)
    return bool(browser_agent.verify(expect["kind"], expect["value"]))


# --------------------------------------------------------------------------
# desktop (delegates to evo.automation.desktop_agent — moved unchanged)
# --------------------------------------------------------------------------

def _execute_desktop(payload: dict) -> dict:
    from evo.automation import desktop_agent

    op = payload.get("op")
    adapter = desktop_agent.PYWINAUTO_ADAPTER
    if op == "launch":
        return adapter.launch_app(payload["app"])
    if op == "type_text":
        return adapter.type_text(payload["text"])
    if op == "press_key":
        return adapter.press_key(payload["key"])
    if op == "close":
        return adapter.close_window(payload["app"])
    if op == "launch_notepad_typed":
        # Fresh instance only — never reuse or touch Suhaib's existing windows.
        # Text is set via UIA ValuePattern: zero keystrokes, zero focus risk.
        launch = adapter.launch_app("notepad", reuse_existing=False)
        if not launch.get("success"):
            return {"success": False, "error": f"launch failed: {launch}", "hwnd": None}
        hwnd = launch.get("hwnd")
        pid = launch.get("pid")
        time.sleep(1.5)  # allow the Win11 XAML shell to finish hosting the editor
        set_result = desktop_agent.set_notepad_text(hwnd, payload["text"])
        if not set_result.get("success"):
            adapter.close_window(hwnd)
            return {"success": False, "error": set_result.get("error"), "hwnd": hwnd}
        return {"success": True, "hwnd": hwnd, "pid": pid}
    raise ValueError(f"unknown desktop op '{op}'")


def _verify_desktop(payload: dict) -> bool:
    from evo.automation import desktop_agent

    expect = _require_expect(payload)
    adapter = desktop_agent.PYWINAUTO_ADAPTER
    kind = expect["kind"]
    if kind == "window_exists":
        return len(adapter.find_windows_by_app(expect["value"])) > 0
    if kind == "window_gone":
        return len(adapter.find_windows_by_app(expect["value"])) == 0
    if kind == "notepad_content_contains":
        hwnd = payload.get("hwnd")
        pid = payload.get("pid")
        read = desktop_agent.read_notepad_text(hwnd)  # live UIA value re-check
        close = adapter.close_window(hwnd) if hwnd else {"success": True}
        if hwnd and not close.get("verified_closed") and pid:
            # Dirty-doc save prompt can block WM_CLOSE on packaged apps; this pid
            # belongs to the instance THIS action launched, so force-close is scoped.
            desktop_agent.force_close_pid(pid)
        if not read.get("success"):
            raise AssertionError(f"content read-back refused/failed: {read.get('error')}")
        return expect["value"] in read.get("content", "")
    raise ValueError(f"unknown desktop verification kind '{kind}'")


# --------------------------------------------------------------------------
# code (filesystem-backed until Phase F adds LLM generation on top)
# --------------------------------------------------------------------------

def _execute_code(payload: dict) -> dict:
    op = payload.get("op")
    path = Path(payload["path"])
    if op == "write_file":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload["content"], encoding="utf-8")
        return {"written": str(path)}
    if op == "append_text":
        with path.open("a", encoding="utf-8") as fh:
            fh.write(payload["content"])
        return {"appended_to": str(path)}
    raise ValueError(f"unknown code op '{op}'")


def _verify_code(payload: dict) -> bool:
    expect = _require_expect(payload)
    path = Path(payload["path"])
    kind = expect["kind"]
    if kind == "file_contains":
        return path.exists() and expect["value"] in path.read_text(encoding="utf-8")
    if kind == "file_exists":
        return path.exists()
    raise ValueError(f"unknown code verification kind '{kind}'")


# --------------------------------------------------------------------------
# skill (library files under evo/skills/library/<slug>/)
# --------------------------------------------------------------------------

LIBRARY_ROOT = Path(__file__).resolve().parent.parent / "skills" / "library"


def _execute_skill(payload: dict) -> dict:
    from evo.skills.skill_manager import SkillManager

    topic = payload["topic"]
    skill = SkillManager().learn(topic)
    return {"learned": skill.slug}


def _verify_skill(payload: dict) -> bool:
    expect = _require_expect(payload)
    workflow_path = LIBRARY_ROOT / expect["value"] / "workflow.json"
    if not workflow_path.exists():
        return False
    steps = json.loads(workflow_path.read_text(encoding="utf-8")).get("steps", [])
    return len(steps) >= int(expect.get("min_steps", 3))
