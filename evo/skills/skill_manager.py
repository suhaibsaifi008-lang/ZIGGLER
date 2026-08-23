"""Learn / store / retrieve skills (Section 5).

learn(topic): web research (browser_agent) -> LLM synthesis -> structured
workflow.json + notes.md + sources.json under skills/library/<slug>/.
apply(topic, task): feeds the stored workflow into the orchestrator as context.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from evo.core.action_schema import GoalResult  # noqa: F401 (used in apply() annotation)
from evo.core.llm_client import LLMRouter, LLMError

LIBRARY_ROOT = Path(__file__).resolve().parent / "library"


class Skill:
    def __init__(self, slug: str):
        self.slug = slug
        self.dir = LIBRARY_ROOT / slug

    @property
    def workflow_path(self) -> Path:
        return self.dir / "workflow.json"

    def load_workflow(self) -> dict:
        if not self.workflow_path.exists():
            return {"topic": self.slug, "steps": []}
        return json.loads(self.workflow_path.read_text(encoding="utf-8"))


def _slugify(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-") or "untitled"


def list_known_skills() -> list[str]:
    if not LIBRARY_ROOT.exists():
        return []
    return sorted(
        d.name for d in LIBRARY_ROOT.iterdir() if d.is_dir() and (d / "workflow.json").exists()
    )


def _research(topic: str, max_chars: int = 4000) -> tuple[str, list[str]]:
    """Gather how-to material. Uses the automation browser; degrades gracefully.
    Always closes the browser afterwards so no driver outlives the call."""
    sources: list[str] = []
    material = ""
    try:
        from evo.automation import browser_agent

        try:
            browser_agent.navigate(f"https://en.wikipedia.org/wiki/{topic.replace(' ', '_')}")
            page = browser_agent.read(max_chars=max_chars // 2)
            material += f"WIKIPEDIA {page.get('title', '')}:\n{page.get('text', '')}\n\n"
            sources.append(page.get("url", "wikipedia"))
        except Exception:
            pass
        try:
            summary = browser_agent.search_web(f"{topic} step by step tutorial")
            material += f"WEB SEARCH:\n{summary}\n"
        except Exception:
            pass
    finally:
        try:
            from evo.automation import browser_agent

            browser_agent.close()
        except Exception:
            pass
    return material, sources


def _synthesize_steps(topic: str, material: str) -> dict:
    router = LLMRouter()
    prompt = (
        f"Topic: {topic}\n\nResearch notes:\n{material[:2200]}\n\n"
        "Extract a practical step-by-step workflow for using "
        f"{topic}. Respond with ONLY minified JSON of shape:\n"
        '{"steps":[{"n":1,"action":"...","detail":"short concrete instruction"}],'
        '"shortcuts":[],"notes":[]}\n'
        "Rules: exactly 5 steps, each action concrete and specific to "
        f"{topic}, no preamble, no markdown."
    )
    raw = ""
    last_exc: Exception | None = None
    for _ in range(2):  # one retry: small local models occasionally emit broken JSON
        try:
            raw = router.complete(prompt).text.strip()
            raw = re.sub(r"^```(?:json)?|```$", "", raw).strip()
            data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
            return data
        except Exception as exc:
            last_exc = exc
            prompt += "\nREMINDER: respond with ONLY valid minified JSON, no other text."
    raise RuntimeError(f"LLM could not produce structured workflow: {last_exc}")


class SkillManager:
    def learn(self, topic: str) -> Skill:
        topic = topic.strip()
        slug = _slugify(topic)
        skill = Skill(slug)
        skill.dir.mkdir(parents=True, exist_ok=True)

        material, sources = _research(topic)
        try:
            workflow_data = _synthesize_steps(topic, material)
        except LLMError as exc:
            raise RuntimeError(f"cannot learn '{topic}' without an LLM backend: {exc}") from exc

        steps = [
            {"n": i + 1, **{k: s.get(k, "") for k in ("action", "detail")}}
            for i, s in enumerate(workflow_data.get("steps", []))
        ]
        payload = {
            "topic": topic,
            "slug": slug,
            "created_at": time.time(),
            "steps": steps,
            "shortcuts": workflow_data.get("shortcuts", []),
            "notes": workflow_data.get("notes", []),
        }
        skill.workflow_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (skill.dir / "notes.md").write_text(
            f"# {topic}\n\nLearned: {time.strftime('%Y-%m-%d %H:%M')}\n\n"
            + "\n".join(f"- {s['n']}. {s['action']} — {s['detail']}" for s in steps),
            encoding="utf-8",
        )
        (skill.dir / "sources.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
        return skill

    def apply(self, topic: str, task: str) -> GoalResult:
        from evo.core.orchestrator import handle_goal

        slug = _slugify(topic)
        if slug not in list_known_skills():
            self.learn(topic)
        workflow = Skill(slug).load_workflow()
        # The LLM planner receives the workflow steps as mandatory context; the
        # resulting plan is expected to reference them (Section 5 acceptance).
        return handle_goal(task, {"skill_hint": workflow})

    def list_known_skills(self) -> list[str]:
        return list_known_skills()
