"""Text-to-speech via edge-tts (neural, free) with offline beep fallback."""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path

VOICE = os.environ.get("ZIGGLER_TTS_VOICE", "en-GB-RyanNeural")  # Jarvis-ish British male


def synthesize_to_file(text: str, out_path: str | None = None, voice: str = VOICE) -> str:
    """Render speech to an MP3 and return its path."""
    import edge_tts

    out = out_path or str(Path(tempfile.gettempdir()) / f"ziggler_{int(time.time()*1000)}.mp3")

    async def _run() -> None:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(out)

    asyncio.run(_run())
    if not Path(out).exists():
        raise RuntimeError("edge-tts produced no file")
    return out


def speak(text: str, voice: str = VOICE, block: bool = True) -> bool:
    """Speak text aloud. Returns True when playback started/completed."""
    try:
        path = synthesize_to_file(text, voice=voice)
    except Exception as exc:
        import logging

        logging.getLogger("ziggler.tts").warning("synthesize failed: %s", exc)
        return False

    def _play_windows() -> None:
        # Default MP3 handler plays without extra dependencies.
        os.startfile(path)  # noqa: S606

    _play_windows()
    if block:
        time.sleep(min(12.0, 1.2 + len(text) / 14.0))  # rough duration; keeps loop pacing
    return True


def speak_sync(text: str, voice: str = VOICE) -> bool:
    """Blocking playback using a background PowerShell player (more precise than startfile)."""
    try:
        path = synthesize_to_file(text, voice=voice)
    except Exception:
        return False
    import subprocess

    ps = (
        "Add-Type -AssemblyName PresentationCore;"
        f"$p=New-Object System.Windows.Media.MediaPlayer;"
        f"$p.Open([Uri]'{Path(path).as_uri()}');"
        "$p.Play(); Start-Sleep -Milliseconds 400;"
        "while(-not $p.Position.HasEnded -and $p.NaturalDuration.HasTimeSpan){"
        "if($p.Position.TotalSeconds -ge $p.NaturalDuration.TimeSpan.TotalSeconds){break};"
        "Start-Sleep -Milliseconds 200}"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=max(30, len(text)), capture_output=True)
    return True
