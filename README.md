# ZIGGLER — personal assistant (Jarvis-style)

Python 3.11+ · Playwright (browser) · pywinauto/UIA (desktop) · vosk (STT) · edge-tts (voice)
· Ollama + FreeLLMAPI gateway (LLM routing with fallbacks)

## Run
```
start-ziggler.cmd            :: gateway + web harness (http://127.0.0.1:8765)
python evo/main.py --chat    :: CLI assistant
python evo/main.py --voice   :: wake words "Ziggler" / "Jarvis" -> STT -> brain -> TTS
python evo/main.py --dry-run :: import check
python -m pytest tests/      :: test suite
```

## Layout
```
evo/
  core/        orchestrator, intents, pipeline, llm_client, memory_store, money_mode
  automation/  browser_agent (Playwright), desktop_agent (pywinauto/UIA substrate)
  coder/       code_agent (self-editing w/ compile verification), site_builder
  skills/      skill_manager — learn(topic) via web research -> workflow.json
  voice/       wake_word, stt (vosk), tts (edge-tts)
  webui/       stdlib HTTP harness: chat / abilities / goal runner / models
  data/        flat-file memory + settings (settings.json is gitignored — see example)
  tests/       pytest suite
```

## Security notes
- `evo/data/settings.json` holds your gateway key — never committed (see settings.example.json).
- `evo/data/memory.json` holds your personal facts/reminders — never committed.
- Desktop actions use UIA ValuePattern instead of keystrokes; fresh app instances only.
