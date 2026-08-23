"""Phase E acceptance: learn('Canva') -> workflow.json with >=3 concrete steps;
apply() produces an orchestrator plan referencing at least one workflow step."""
import json
import re

import pytest

from evo.core.llm_client import LLMRouter
from evo.skills.skill_manager import LIBRARY_ROOT, SkillManager


def _backend_ready() -> bool:
    try:
        return LLMRouter().is_available()
    except Exception:
        return False


@pytest.mark.skipif(not _backend_ready(), reason="no LLM backend available")
def test_canva_learn_and_apply_acceptance():
    manager = SkillManager()
    manager.learn("Canva")

    workflow_path = LIBRARY_ROOT / "canva" / "workflow.json"
    assert workflow_path.exists(), "workflow.json must exist after learn()"
    data = json.loads(workflow_path.read_text(encoding="utf-8"))
    steps = data.get("steps", [])
    assert len(steps) >= 3, "at least 3 concrete steps required"
    filler = ("step 1", "do it", "etc")
    for s in steps:
        text = f"{s.get('action', '')} {s.get('detail', '')}".lower()
        assert len(s.get("action", "")) >= 5, f"step too generic: {s}"
        assert not any(f == text.strip() for f in filler)

    result = manager.apply("Canva", "make a birthday card in Canva")
    plan_blob = " ".join(a.description.lower() for a in result.plan).lower()
    step_tokens = set()
    for s in steps:
        for word in re.findall(r"[a-z]{5,}", (s.get("action", "") + " " + s.get("detail", "")).lower()):
            step_tokens.add(word)
    overlap = {w for w in re.findall(r"[a-z]{5,}", plan_blob) if w in step_tokens}
    assert overlap, (
        "orchestrator plan must reference at least one workflow step; "
        f"plan={ [a.description for a in result.plan] }"
    )
