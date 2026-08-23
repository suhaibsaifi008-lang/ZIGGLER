"""Phase D acceptance: one REAL desktop action (launch fresh Notepad, type text)
verified by reading back the window's ACTUAL content via select-all + copy.

Safety: uses reuse_existing=False so existing Notepad windows are never touched,
refuses to send keystrokes unless foreground focus is verified, and closes only
the instance it opened."""
import time

from evo.core.action_schema import GoalResult
from evo.core.orchestrator import handle_goal

SENTINEL = "ZIGGLER_PHASE_D_SENTINEL_7Q4"


def test_notepad_type_and_read_back_real_content():
    result = handle_goal(
        "notepad_roundtrip",
        {
            "plan": [
                {
                    "kind": "desktop",
                    "description": "Launch fresh Notepad, type sentinel, verify by reading real content",
                    "payload": {
                        "op": "launch_notepad_typed",
                        "text": SENTINEL,
                        "expect": {"kind": "notepad_content_contains", "value": SENTINEL},
                    },
                }
            ]
        },
    )
    assert isinstance(result, GoalResult)
    assert result.success is True, f"failure_reason: {result.failure_reason}"
    assert result.completed_steps[0].verify is not None


def test_verify_rejects_wrong_content():
    """Negative control: expect a sentinel that was never typed — verification must
    fail against the REAL window content instead of returning True."""
    result = handle_goal(
        "notepad_roundtrip_negative",
        {
            "plan": [
                {
                    "kind": "desktop",
                    "description": "Type sentinel but expect content that cannot be there",
                    "payload": {
                        "op": "launch_notepad_typed",
                        "text": SENTINEL,
                        "expect": {"kind": "notepad_content_contains", "value": "NEVER_TYPED_XYZ_31"},
                    },
                }
            ]
        },
    )
    assert result.success is False
    assert "failed verification" in (result.failure_reason or "")


def test_no_stray_notepad_windows_left_behind():
    from evo.automation import desktop_agent

    time.sleep(1.0)  # allow any close from prior tests to settle
    real_notepads = [
        w for w in desktop_agent.PYWINAUTO_ADAPTER.list_windows()
        if w["class_name"] == "Notepad"
    ]
    assert real_notepads == []
