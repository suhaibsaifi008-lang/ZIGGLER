"""Ziggler web test-harness: chat + goal runner + ability enumeration.

Stdlib-only HTTP server (Section 0: simplicity). One responsibility: expose the
existing core modules over HTTP for browser testing — no business logic here.
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_STATIC_DIR = Path(__file__).resolve().parent / "static"

ABILITY_CATALOG = {
    "orchestrator": {
        "status": "live — rule intents + LLM planner",
        "endpoint": "POST /api/goal",
        "contract": "goal -> plan -> execute -> verify(); stops at first failed step",
    },
    "intents": {
        "status": "live (instant, offline-capable)",
        "ops": ["time/date", "weather", "briefing", "news headlines", "remember/recall facts",
                "reminders + timers", "notes/todos", "calculator", "wikipedia instant answers",
                "dictionary", "battery/cpu", "screenshot", "volume", "brightness",
                "media keys (play/pause/skip)", "clipboard read/copy", "set my city",
                "open/close <app>", "find file", "search web", "maps", "summarize URL",
                "lock PC", "play <song>"],
        "example_goal": "briefing / who is Nikola Tesla / remind me in 10 minutes to stretch",
    },
    "pipeline": {
        "status": "live — shared brain for voice/CLI/web",
        "contract": "respond(text): intents first, then LLM with memory context",
    },
    "memory_store": {
        "status": "live (flat JSON)",
        "ops": ["facts", "preferences", "conversation history", "reminders"],
    },
    "browser_agent": {
        "status": "live (Playwright/Chromium)",
        "ops": ["navigate", "click", "fill", "read", "search_web"],
        "verify_kinds": ["url_contains", "title_contains", "text_on_page", "element_visible"],
        "example_goal": "demo_browser_navigate",
    },
    "desktop_agent": {
        "status": "live (pywinauto/UIA)",
        "ops": ["launch", "type_text", "press_key", "close", "launch_notepad_typed"],
        "verify_kinds": ["window_exists", "window_gone", "notepad_content_contains"],
        "safety": "fresh instances only; UIA ValuePattern instead of keystrokes; closes only what it opened",
    },
    "code_agent": {
        "status": "live — LLM writes functions, compile-verified before saving",
        "ops": ["write_function", "edit_file"],
        "safety": "self-edit of Ziggler source requires explicit approval",
    },
    "site_builder": {"status": "live", "ops": ["scaffold static site from spec"]},
    "skill_manager": {
        "status": "live — learn via web research + LLM synthesis (Canva acceptance passed)",
        "ops": ["learn(topic)", "apply(topic, task)", "list_known_skills()"],
    },
    "voice": {
        "status": "live — wake word + STT (vosk) + TTS (edge-tts neural)",
        "ops": ["run_forever()", "wake words: 'Ziggler' / 'Jarvis'"],
        "cli": "python evo/main.py --voice",
    },
    "money_mode": {
        "status": "live — scans remote-job feeds, scores vs your skills",
        "ops": ["money report", "set my money skills to ...", "draft proposal N"],
        "honest_contract": "finds leads + drafts proposals; Suhaib sends/approves anything involving accounts or money",
    },
    "llm_router": {
        "chain": ["FreeLLMAPI gateway (primary)", "Groq free tier", "Ollama local (fallback)"],
        "note": "FreeLLMAPI needs >=1 upstream provider key in its dashboard before completions route there",
    },
}


class ZigglerHandler(BaseHTTPRequestHandler):
    server_version = "ZigglerWebUI/0.1"

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    # ------------------------------------------------------------------ GET
    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            page = (_STATIC_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
        elif path == "/api/abilities":
            self._send_json({"abilities": ABILITY_CATALOG, **self._gateway_status()})
        elif path == "/api/models":
            client = self._freellmapi_client()
            models = client.list_models() if client else []
            self._send_json({"count": len(models), "models": sorted(m["id"] for m in models)})
        elif path == "/api/health":
            self._send_json({"ok": True})
        else:
            self._send_json({"error": f"unknown path {path}"}, status=404)

    # ----------------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        payload = self._read_json()
        try:
            if path == "/api/chat":
                from evo.core.pipeline import respond

                message = (payload.get("message") or "").strip()
                if not message:
                    return self._send_json({"error": "empty message"}, status=400)
                reply = respond(message)
                return self._send_json({"reply": reply, "backend": "ziggler-pipeline"})
            if path == "/api/goal":
                from evo.core.orchestrator import handle_goal
                from evo.core.permissions import check

                plan = payload.get("context", {}).get("plan") or []
                kinds = {a.get("kind") for a in plan if isinstance(a, dict)}
                denied = [k for k in kinds if not check(k)]
                if denied:
                    return self._send_json(
                        {"error": f"permission tier forbids: {', '.join(sorted(denied))}"},
                        status=403,
                    )
                result = handle_goal(payload.get("goal", ""), payload.get("context") or {})
                return self._send_json(
                    {
                        "success": result.success,
                        "completed_steps": [a.description for a in result.completed_steps],
                        "failure_reason": result.failure_reason,
                    }
                )
            return self._send_json({"error": f"unknown path {path}"}, status=404)
        except Exception:
            # Friendly surface text; details go to the server log, not the chat UI.
            import logging

            logging.getLogger("ziggler.webui").exception("handler error on %s", path)
            self._send_json(
                {"error": "Something went wrong running that. Check the Ziggler log for details."},
                status=500,
            )

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _freellmapi_client():
        try:
            from evo.core.llm_client import FreeLLMAPIClient

            return FreeLLMAPIClient()
        except Exception:
            return None

    def _gateway_status(self) -> dict:
        client = self._freellmapi_client()
        live = bool(client and client.is_available())
        models = client.list_models() if client else []
        return {
            "gateway": {
                "url": client.base_url if client else None,
                "reachable": live,
                "model_count": len(models),
                "note": "" if live else "gateway unreachable — add provider keys / start it with start-gateway.cmd",
            }
        }

    def log_message(self, fmt: str, *args) -> None:  # quiet
        pass


def serve(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), ZigglerHandler)
    print(f"Ziggler test harness: http://{host}:{port}  (Ctrl+C to stop)")
    httpd.serve_forever()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="ziggler-webui")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    serve(args.host, args.port)
