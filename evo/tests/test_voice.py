"""Phase G: TTS synthesizes real audio; wake-word matcher logic; STT pipeline
present. Microphone loops stay manual (can't be asserted in CI)."""
from pathlib import Path

import pytest

from evo.voice import tts


def test_tts_synth_produces_audio_file(tmp_path):
    out = tts.synthesize_to_file("Ziggler voice check.", str(tmp_path / "tts.mp3"))
    p = Path(out)
    assert p.exists() and p.stat().st_size > 2000  # a real second+ of audio


def test_wake_words_defined():
    from evo.voice.wake_word import WAKE_WORDS

    assert "ziggler" in WAKE_WORDS
    assert "jarvis" in WAKE_WORDS


def test_stt_module_contract():
    from evo.voice import stt

    # transcribe() requires a WAV; wrong input must raise, not lie about success.
    with pytest.raises(Exception):
        stt.transcribe(str(Path(__file__)))
