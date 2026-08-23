"""Speech-to-text via Vosk (offline). Auto-downloads a small English model."""
from __future__ import annotations

import json
import wave
import zipfile
from pathlib import Path

import urllib.request

MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.22.zip"


def _model_path() -> Path:
    return MODEL_DIR / "vosk-model-small-en-us-0.22"


def ensure_model() -> str:
    """Download/extract the vosk model once; return its path."""
    target = _model_path()
    if target.exists():
        return str(target)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    archive = MODEL_DIR / "model.zip"
    urllib.request.urlretrieve(MODEL_URL, archive)  # noqa: F821
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(MODEL_DIR)
    archive.unlink()
    return str(target)


def transcribe(audio_path: str) -> str:
    """Transcribe a 16kHz mono WAV file to text (offline)."""
    from vosk import Model, KaldiRecognizer

    model = Model(_model_path().as_posix() if _model_path().exists() else ensure_model())
    with wave.open(audio_path, "rb") as wf:
        rec = KaldiRecognizer(model, wf.getframerate())
        rec.SetWords(False)
        chunks: list[str] = []
        while True:
            data = wf.readframes(8000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                chunks.append(json.loads(rec.Result()).get("text", ""))
        chunks.append(json.loads(rec.FinalResult()).get("text", ""))
    return " ".join(c for c in chunks if c).strip()


def listen(timeout_seconds: float = 6.0, phrase_limit: float = 6.0) -> str:
    """Capture from the default microphone and transcribe."""
    import queue as _queue

    import sounddevice as sd

    from vosk import Model, KaldiRecognizer

    model = Model(ensure_model())
    samplerate = 16000
    q: "_queue.Queue[bytes]" = _queue.Queue()

    def callback(indata, frames, time_info, status):
        q.put(bytes(indata))

    rec = KaldiRecognizer(model, samplerate)
    heard = ""
    import time as _time

    deadline = _time.time() + timeout_seconds
    with sd.RawInputStream(samplerate=samplerate, blocksize=4000, dtype="int16",
                           channels=1, callback=callback):
        while _time.time() < deadline:
            try:
                data = q.get(timeout=0.5)
            except _queue.Empty:
                continue
            if rec.AcceptWaveform(data):
                heard = json.loads(rec.Result()).get("text", "")
                if heard:
                    break
    if not heard:
        heard = json.loads(rec.FinalResult()).get("text", "")
    return heard.strip()


def listen_until_wake(wake_words: tuple[str, ...] = ("ziggler",), idle_timeout: float = 60.0) -> str | None:
    """Continuous loop: waits for a wake word, returns the rest of that sentence.

    Returns None only when nothing was heard before idle_timeout elapsed.
    """
    import queue as _queue
    import time as _time

    import sounddevice as sd

    from vosk import Model, KaldiRecognizer

    model = Model(ensure_model())
    q: "_queue.Queue[bytes]" = _queue.Queue()
    rec = KaldiRecognizer(model, 16000)

    def callback(indata, frames, time_info, status):
        q.put(bytes(indata))

    started = _time.time()
    with sd.RawInputStream(samplerate=16000, blocksize=4000, dtype="int16",
                           channels=1, callback=callback):
        while _time.time() - started < idle_timeout:
            try:
                data = q.get(timeout=0.5)
            except _queue.Empty:
                continue
            if not rec.AcceptWaveform(data):
                partial = json.loads(rec.PartialResult()).get("partial", "")
                lowered = partial.lower()
                for wake in wake_words:
                    if wake in lowered:
                        tail = lowered.split(wake, 1)[1].strip(" ,.!?")
                        return tail or "__WAKE_ONLY__"
            else:
                result = json.loads(rec.Result()).get("text", "").lower()
                for wake in wake_words:
                    if wake in result:
                        tail = result.split(wake, 1)[1].strip(" ,.!?")
                        return tail or "__WAKE_ONLY__"
    return None
