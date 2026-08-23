"""Phase C acceptance: one REAL Playwright action end-to-end through verify(),
plus a negative control proving verify() inspects live page state instead of
returning True unconditionally."""
import socket

import pytest

from evo.core.action_schema import Action, GoalResult
from evo.core.orchestrator import handle_goal


def _online() -> bool:
    try:
        socket.create_connection(("example.com", 443), timeout=3).close()
        return True
    except OSError:
        return False


def test_goalresult_and_action_are_dataclasses():
    result = GoalResult(success=False)
    assert result.completed_steps == []
    assert result.failure_reason is None
    action = Action(kind="browser", description="d", payload={})
    with pytest.raises(ValueError):
        action.verify()


@pytest.mark.skipif(not _online(), reason="network unreachable")
def test_single_browser_action_end_to_end():
    result = handle_goal("demo_browser_navigate", {})
    assert isinstance(result, GoalResult)
    assert result.success is True, f"failure_reason: {result.failure_reason}"
    assert len(result.completed_steps) == 1
    assert result.failure_reason is None


@pytest.mark.skipif(not _online(), reason="network unreachable")
def test_verify_detects_wrong_page_state():
    """Negative control: same navigation but an expectation that CANNOT hold.
    If verify() just returned True this would pass — it must fail instead."""
    result = handle_goal(
        "demo_browser_navigate",
        {
            "plan": [
                {
                    "kind": "browser",
                    "description": "Navigate to example.com expecting a sentinel that is absent",
                    "payload": {
                        "op": "navigate",
                        "url": "https://example.com",
                        "expect": {"kind": "text_on_page", "value": "ZIGGLER_SENTINEL_NOT_PRESENT_9f2"},
                    },
                }
            ]
        },
    )
    assert result.success is False
    assert result.failure_reason is not None
    assert "failed verification" in result.failure_reason
    assert result.completed_steps == []


def test_unknown_goal_gets_planned_or_reports_honestly():
    """Unknown goals engage the LLM planner — Ziggler attempts ANY goal. The
    contract is a well-formed GoalResult either way."""
    result = handle_goal("no such goal exists", {})
    assert isinstance(result.success, bool)
    if not result.success:
        assert result.failure_reason
