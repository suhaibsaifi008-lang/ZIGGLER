"""MONEY MODE — opportunity scanner and asset generator.

Honest contract: Ziggler finds leads, drafts proposals and builds sellable
assets; Suhaib approves anything involving accounts, sending, or money.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request

from evo.core import memory_store

FEEDS = {
    "remotive": "https://remotive.com/api/remote-jobs?limit=20",
}

DEFAULT_SKILLS = ["python", "web", "automation", "writing", "data entry", "design"]


def _fetch(url: str, timeout: float = 12.0):
    req = urllib.request.Request(url, headers={"User-Agent": "ziggler/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_skills() -> list[str]:
    raw = memory_store.get_preference("money_skills", "")
    return [s.strip().lower() for s in raw.split(",") if s.strip()] or DEFAULT_SKILLS


def set_skills(csv_skills: str) -> None:
    memory_store.set_preference("money_skills", csv_skills)


def _score(job_title: str, job_desc: str, skills: list[str]) -> int:
    blob = f"{job_title} {job_desc}".lower()
    return sum(1 for s in skills if s in blob)


def scan(max_leads: int = 8) -> list[dict]:
    """Fetch remote-job feeds, score against configured skills, persist top leads."""
    skills = get_skills()
    candidates: list[dict] = []
    try:
        data = json.loads(_fetch(FEEDS["remotive"]))
        for job in data.get("jobs", []):
            candidates.append({
                "title": job.get("title", ""),
                "company": job.get("company_name", ""),
                "url": job.get("url", ""),
                "snippet": re.sub(r"<[^>]+>", " ", job.get("description", ""))[:220].strip(),
                "source": "remotive",
            })
    except Exception:
        pass

    scored = []
    seen_titles = set()
    for c in candidates:
        key = c["title"].lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        score = _score(c["title"], c["snippet"], skills)
        if score > 0:
            scored.append({**c, "score": score})
    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:max_leads]

    if top:
        memory_store.set_preference(
            "money_leads", json.dumps({"updated": time.time(), "leads": top})
        )
    return top


def current_leads() -> list[dict]:
    raw = memory_store.get_preference("money_leads", "")
    if not raw:
        return []
    return json.loads(raw).get("leads", [])


def report() -> str:
    leads = scan() or current_leads()
    if not leads:
        return (
            "No matching leads right now. Tell me your skills with "
            "'set my money skills to python, writing, design' and I'll rescan."
        )
    lines = [
        f"{i + 1}. [{l['score']}] {l['title']} at {l['company']} — {l['url']}"
        for i, l in enumerate(leads)
    ]
    return f"{len(lines)} fresh opportunities:\n" + "\n".join(lines)


def draft_proposal(lead_number: int) -> str:
    """LLM-drafted proposal for a stored lead — Suhaib reviews before sending."""
    leads = current_leads()
    if not leads or not 1 <= lead_number <= len(leads):
        return "Run 'money report' first, then 'draft proposal 1'."
    lead = leads[lead_number - 1]
    from evo.core.llm_client import LLMRouter

    prompt = (
        "Write a short, human freelance proposal (max 120 words) for this job.\n"
        f"Title: {lead['title']}\nCompany: {lead['company']}\nSnippet: {lead['snippet']}\n"
        "Tone: confident, specific, no fluff, end with a question."
    )
    try:
        draft = LLMRouter().complete(prompt).text.strip()
    except Exception as exc:
        return f"Proposal drafting needs an LLM backend ({exc})."
    memory_store.add_message("assistant", f"PROPOSAL DRAFT for '{lead['title']}':\n{draft}")
    return f"DRAFT (review before sending anywhere):\n{draft}"


# ------------------------------------------------------------------ intent hook

def handle_money_command(text: str) -> str | None:
    t = text.lower()
    if re.search(r"\bmoney (report|mode|leads)\b|\bscan (remote )?(jobs|gigs)\b|\bfind me work\b", t):
        return report()
    m = re.search(r"draft (?:a )?proposal\s*(?:for )?(?:lead\s*)?#?(\d+)", t)
    if m:
        return draft_proposal(int(m.group(1)))
    m = re.search(r"set my money skills to (.+)", t)
    if m:
        set_skills(m.group(1))
        return f"Skills saved: {m.group(1)}. Say 'money report' anytime."
    return None
