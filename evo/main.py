"""Ziggler entry point — wires everything together.

Phase A contract: `python evo/main.py --dry-run` imports every module with no errors.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

MODULES = [
    "evo.core.action_schema",
    "evo.core.llm_client",
    "evo.core.memory_store",
    "evo.core.permissions",
    "evo.core.orchestrator",
    "evo.core.intents",
    "evo.core.pipeline",
    "evo.automation.browser_agent",
    "evo.automation.desktop_agent",
    "evo.coder.code_agent",
    "evo.coder.site_builder",
    "evo.skills.skill_manager",
    "evo.voice.wake_word",
    "evo.voice.stt",
    "evo.voice.tts",
    "evo.webui.server",
]


def dry_run() -> int:
    failures: list[str] = []
    for module in MODULES:
        try:
            importlib.import_module(module)
            print(f"  ok   {module}")
        except Exception as exc:
            failures.append(module)
            print(f"  FAIL {module}: {exc}")
    if failures:
        print(f"dry-run FAILED for {len(failures)} module(s): {', '.join(failures)}")
        return 1
    print(f"dry-run OK: {len(MODULES)}/{len(MODULES)} modules imported cleanly")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="ziggler")
    parser.add_argument("--dry-run", action="store_true", help="import every module and exit")
    parser.add_argument("--chat", action="store_true", help="interactive CLI assistant")
    parser.add_argument("--voice", action="store_true", help="full voice loop: wake word -> STT -> respond -> TTS")
    parser.add_argument("--web", action="store_true", help="start the browser test harness on :8765")
    args = parser.parse_args()

    if args.dry_run:
        return dry_run()
    if args.web:
        from evo.webui.server import serve

        serve()
        return 0
    if args.chat:
        return _chat_loop()
    if args.voice:
        return _voice_loop()
    parser.print_help()
    return 2


def _chat_loop() -> int:
    from evo.core.pipeline import respond

    print("Ziggler chat. Commands work instantly (time, weather, open notepad, "
          "remind me in 5 minutes to..., remember x is y, play <song>, ...). "
          "Type 'exit' to quit.")
    while True:
        try:
            text = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ("exit", "quit"):
            break
        if not text:
            continue
        print(f"Ziggler> {respond(text)}")
    return 0


def _voice_loop() -> int:  # pragma: no cover - interactive
    from evo.core.pipeline import respond
    from evo.voice.wake_word import run_forever

    run_forever(respond)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
