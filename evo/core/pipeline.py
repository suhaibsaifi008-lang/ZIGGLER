"""Unified response pipeline: the single brain shared by voice, CLI, and web.

pipeline.respond(text) -> reply string
  1. rule-based intent engine (instant, offline-capable)
  2. LLM conversation with long-term memory context (router w/ fallbacks)
Every turn is stored in memory_store so Ziggler remembers the conversation.
"""
from __future__ import annotations

from evo.core import intents, llm_client, memory_store


def _memory_context() -> str:
    history = memory_store.recent_history(10)
    if not history:
        return ""
    lines = [f"{h['role'].upper()}: {h['content']}" for h in history]
    return "\n".join(lines)[-3000:]


def respond(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""

    # 1. deterministic Jarvis commands
    result = intents.handle_command(text)
    if result is not None and result.actioned:
        memory_store.add_message("user", text)
        memory_store.add_message("assistant", result.text)
        return result.text

    # 1b. money mode commands
    money_reply = money_mode.handle_money_command(text)
    if money_reply is not None:
        memory_store.add_message("user", text)
        memory_store.add_message("assistant", money_reply)
        return money_reply

    # 2. LLM fallback with conversational + factual memory
    memory_store.add_message("user", text)
    facts = memory_store.search_facts(text)
    prompt_parts = []
    if facts:
        fact_block = "; ".join(f"{k} = {v}" for k, v in list(facts.items())[:5])
        prompt_parts.append(f"Known facts about the user: {fact_block}")
    context_block = _memory_context()
    if context_block:
        prompt_parts.append(f"Recent conversation:\n{context_block}")
    prompt_parts.append(f"User: {text}\nAnswer briefly as Ziggler, a capable personal assistant.")
    try:
        reply = llm_client.LLMRouter().complete("\n\n".join(prompt_parts)).text.strip()
    except Exception as exc:
        reply = f"My LLM backends are unreachable right now ({exc}). Rule-based commands still work."
    memory_store.add_message("assistant", reply)
    return reply
