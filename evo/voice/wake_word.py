"""Wake-word loop: "Ziggler" (or "Jarvis") -> capture command -> dispatch."""
from __future__ import annotations

import time

WAKE_WORDS = ("ziggler", "jarvis")

from evo.voice import stt, tts  # noqa: E402


def wake_keywords() -> tuple[str, ...]:
    return WAKE_WORDS


def run_forever(pipeline=None) -> None:  # pragma: no cover - interactive loop
    """Blocking assistant loop. `pipeline(text) -> reply str` handles commands."""
    tts.speak("Ziggler online.")
    while True:
        tail = stt.listen_until_wake(WAKE_WORDS)
        if not tail:
            continue
        if tail == "__WAKE_ONLY__":
            tts.speak("Yes?")
            tail = stt.listen(timeout_seconds=6)
            if not tail:
                tts.speak("Never mind then.")
                continue
        reply = pipeline(tail) if pipeline else f"Heard: {tail}"
        tts.speak(reply or "Done.")


def once(pipeline) -> str | None:
    """Single wake->command->reply cycle; useful for tests and the web UI."""
    tail = stt.listen_until_wake(WAKE_WORDS, idle_timeout=30)
    if not tail:
        return None
    text = "" if tail == "__WAKE_ONLY__" else tail
    if not text:
        text = stt.listen(timeout_seconds=6)
    if not text:
        return "(nothing heard)"
    return pipeline(text)


if __name__ == "__main__":  # pragma: no cover
    from evo.core.pipeline import respond

    print("Wake words:", ", ".join(wake_keywords()))
    run_forever(respond)
