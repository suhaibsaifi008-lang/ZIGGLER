"""Main decision loop: goal -> plan -> actions -> verify (Section 2 contract).

Plans come from three sources, in order:
  1. explicit plan passed via context['plan']
  2. LLM planner (goal + memory + optional skill workflow hints)
  3. hardcoded demo plans
The orchestrator never marks a goal successful without every step's verify()
passing, and stops at the first failed step.
"""
from __future__ import annotations

import json
import re
from typing import Any

from evo.core.action_schema import Action, GoalResult


HARDCODED_PLANS: dict[str, list[Action]] = {
    "demo_browser_navigate": [
        Action(
            kind="browser",
            description="Navigate to example.com and confirm its title text",
            payload={
                "op": "navigate",
                "url": "https://example.com",
                "expect": {"kind": "text_on_page", "value": "Example Domain"},
            },
        ),
    ],
}

_PLANNER_MANUAL = """Available action kinds and ops:
browser: op=navigate{url}, click{desc}, fill{desc,text,submit?}; expect kinds: url_contains|title_contains|text_on_page|element_visible
desktop: op=launch{app}|type_text{text}|press_key{key}|close{app}|launch_notepad_typed{text}; expect kinds: window_exists|window_gone|notepad_content_contains
code: op=write_file{path,content}|append_text{path,content}; expect kinds: file_exists|file_contains
skill: op=learn{topic}; expect kinds: workflow_exists{value=slug,min_steps}
Rules: every action MUST include expect:{kind,value}. Prefer the fewest actions that achieve the goal."""


def _plan_for(goal: str, context: dict) -> list[Action]:
    if "plan" in context and context["plan"]:
        return [p if isinstance(p, Action) else Action(**p) for p in context["plan"]]
    return HARDCODED_PLANS.get(goal, [])


def _plan_with_llm(goal: str, context: dict) -> list[Action] | None:
    from evo.core.llm_client import LLMRouter

    skill_hint = context.get("skill_hint") or {}
    hint_lines = ""
    if skill_hint.get("steps"):
        steps = "; ".join(
            f"{s.get('n')}. {s.get('action')} — {s.get('detail', '')}"[:160]
            for s in skill_hint["steps"][:8]
        )
        hint_lines = (
            f"Use this learned '{skill_hint.get('topic', '')}' workflow — your plan "
            f"steps should follow/reference it:\n{steps}\n"
        )

    prompt = (
        f"Goal: {goal}\n{hint_lines}\n{_PLANNER_MANUAL}\n\n"
        "Respond with ONLY minified JSON: "
        '[{"kind":"browser","description":"...","payload":{...}}, ...]'
    )
    try:
        raw = LLMRouter().complete(prompt).text.strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw).strip()
        data = json.loads(raw[raw.index("["): raw.rindex("]") + 1])
        actions = []
        for item in data[:8]:
            if isinstance(item, dict) and item.get("kind") and item.get("description"):
                actions.append(Action(
                    kind=item["kind"],
                    description=item["description"],
                    payload=item.get("payload") or {},
                ))
        return actions or None
    except Exception:
        return None


def handle_goal(goal: str, context: dict) -> GoalResult:
    """
    1. Get a Plan (ordered Actions): explicit > LLM-planned > hardcoded demos.
    2. Execute each Action via its agent.
    3. After each Action, call that action's own verify() — never assume success.
    4. On failure: stop and report exactly which step failed and why.
    5. Return GoalResult(success, completed_steps, failure_reason).
    """
    plan = _plan_for(goal, context)
    plan_source = "explicit" if plan else "llm"
    if not plan and "plan" not in context:
        plan = _plan_with_llm(goal, context)
        plan_source = "llm"
    if not plan:
        plan = HARDCODED_PLANS.get(goal, [])
        plan_source = "hardcoded" if plan else "none"
    if not plan:
        return GoalResult(False, [], f"no plan available for goal '{goal}'")

    completed: list[Action] = []
    for index, action in enumerate(plan):
        try:
            output = action.execute()
            if isinstance(output, dict):
                for key in ("hwnd", "pid", "written", "learned"):
                    if key in output:
                        action.payload[key] = output[key]
            verified = action.verify()
        except Exception as exc:
            return GoalResult(False, completed,
                              f"step {index} ({action.description}) raised: {exc}", plan)
        if not verified:
            return GoalResult(False, completed,
                              f"step {index} failed verification: {action.description}", plan)
        completed.append(action)

    reason = None
    if plan_source == "llm":
        reason = f"plan executed ({len(plan)} llm-planned step{'s' if len(plan) != 1 else ''})"
    return GoalResult(True, completed, reason, plan)
