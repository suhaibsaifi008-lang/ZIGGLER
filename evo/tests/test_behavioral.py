"""SECTION 2 — Behavioral test matrix.

Every intent category x {happy path, typos/casing, multi-step, ambiguous,
nonexistent target}. Deterministic cases use fakes; live executions are in
tests/test_behavioral_live.py and audit artifacts.
"""
import json
import sys
import types

import evo.automation as automation_pkg
from evo.core import intents, pipeline


def _fake_browser(monkeypatch, results=None):
    """Install a recording fake browser on BOTH import routes."""
    log = {"navigate": [], "click": [], "read": 0}

    class FakeBrowser:
        def navigate(self, url):
            log["navigate"].append(url)
            return {"title": "t", "url": url, "preview": "body text"}

        def click(self, desc):
            if (results or {}).get("click_fails"):
                raise LookupError(f"no element {desc}")
            log["click"].append(desc)
            return {}

        def fill(self, desc, text, submit=False):
            return {}

        def read(self, max_chars=2600):
            log["read"] += 1
            return {"title": "t", "url": "u", "text": "Minecraft official site"}

        def search_web(self, q):
            return (results or {}).get("search", "1. First result about the query")

    fake = FakeBrowser()
    monkeypatch.setattr(automation_pkg, "browser_agent", fake, raising=False)
    monkeypatch.setitem(sys.modules, "evo.automation.browser_agent", fake)
    return log


# ---------------------------------------------------------------- happy paths

def test_happy_open_and_close_app(monkeypatch):
    launched = []
    import evo.automation.desktop_agent as da

    class FakeAdapter:
        def launch_app(self, app, reuse_existing=True):
            launched.append(app)
            return {"success": True}
        def find_windows_by_app(self, app):
            return [{"hwnd": 1}] if app == "notepad" else []
        def close_window(self, target, timeout=3.0):
            return {"success": True, "verified_closed": True}

    monkeypatch.setattr(da, "PYWINAUTO_ADAPTER", FakeAdapter(), raising=False)
    r = intents.handle_command("open notepad")
    assert r is not None and "Notepad" in r.text and launched == ["notepad"]
    r2 = intents.handle_command("close notepad")
    assert r2 is not None and "Closed" in r2.text


def test_search_happy_path(monkeypatch):
    log = _fake_browser(monkeypatch)
    r = intents.handle_command("search for rust programming")
    assert r is not None and "rust programming" in r.text.lower()


def test_search_ddg_fallback_when_bing_interstitials(monkeypatch):
    log = _fake_browser(
        monkeypatch,
        results={"search": "Search page loaded (Loading ...) but no structured results parsed."},
    )
    r = intents.handle_command("search for rust programming")
    assert r is not None
    assert any("duckduckgo" in u for u in log["navigate"]), f"no DDG fallback: {log['navigate']}"


def test_youtube_happy_multistep_with_play(monkeypatch):
    log = _fake_browser(monkeypatch)
    r = intents.handle_command("open youtube and search for minecraft then play the first video")
    assert r and "Playing" in r.text
    assert any("youtube.com/results" in u and "minecraft" in u.lower() for u in log["navigate"])
    assert log["click"], "first-video click must be attempted"


def test_search_on_youtube_wording(monkeypatch):
    """EVO-105 regression: 'search X on YOUTUBE' routes to YouTube, not Bing."""
    log = _fake_browser(monkeypatch)
    r = intents.handle_command("SEARCH FOR MINECRAFT VIDEOS ON YOUTUBE")
    assert r is not None
    assert any("youtube.com/results" in u for u in log["navigate"]), (
        f"expected YouTube navigation, got: {log['navigate']}"
    )


# ------------------------------------------------------------- typos / casing

def test_verb_typo_corrected(monkeypatch):
    launched = []
    import evo.automation.desktop_agent as da

    class FakeAdapter:
        def launch_app(self, app, reuse_existing=True):
            launched.append(app)
            return {"success": True}
        def find_windows_by_app(self, app):
            return []

    monkeypatch.setattr(da, "PYWINAUTO_ADAPTER", FakeAdapter(), raising=False)
    r = intents.handle_command("opne notepad")          # verb typo
    assert r is not None and "Notepad" in r.text
    r2 = intents.handle_command("OPEN   NOTEPAD")       # caps + extra spaces
    assert r2 is not None and launched[-1] == "notepad"


def test_app_typo_corrected(monkeypatch):
    launched = []
    import evo.automation.desktop_agent as da

    class FakeAdapter:
        def launch_app(self, app, reuse_existing=True):
            launched.append(app)
            return {"success": True}
        def find_windows_by_app(self, app):
            return []

    monkeypatch.setattr(da, "PYWINAUTO_ADAPTER", FakeAdapter(), raising=False)
    r = intents.handle_command("open notepa")           # app-name typo
    assert r is not None and launched and launched[0] == "notepad"


def test_query_typos_still_search(monkeypatch):
    log = _fake_browser(monkeypatch)
    r = intents.handle_command("search for minecrft vidoe")
    assert r is not None  # query typos are passed through to the engine


# --------------------------------------------------------- multi-step chains

def test_chain_split_executes_both_halves(monkeypatch):
    events = []
    import evo.automation.desktop_agent as da

    class FakeAdapter:
        def launch_app(self, app, reuse_existing=True):
            events.append(("launch", app))
            return {"success": True}
        def close_window(self, app):
            matches = self.find_windows_by_app(app)
            if matches:
                return {"success": True, "verified_closed": True}
            return {"success": False}
        def find_windows_by_app(self, app):
            return [{"hwnd": 9}] if app == "notepad" else []

    monkeypatch.setattr(da, "PYWINAUTO_ADAPTER", FakeAdapter(), raising=False)
    r = intents.handle_command("open notepad and then close notepad")
    assert r is not None
    assert ("launch", "notepad") in events
    assert "Closed" in r.text


def test_chain_with_noncommand_second_half_goes_to_llm():
    """If ANY half isn't a command, the whole input is conversational.
    ('what is love' WOULD resolve via Wikipedia by design; pick a phrase no
    handler claims.)"""
    assert intents.handle_command("open notepad and explain quantum entanglement poetically") is None


# ------------------------------------------- ambiguous / conversational input

def test_conversational_never_misfires(monkeypatch):
    class FakeResponse:
        text = "Rain is water falling from clouds."
        served_by = "Fake"

    class FakeRouter:
        def __init__(self, *a, **k): pass
        def complete(self, prompt, tools=None): return FakeResponse()
        def is_available(self): return True

    monkeypatch.setattr(pipeline.llm_client, "LLMRouter", FakeRouter)
    for phrase in (
        "tell me about open source software",
        "find out who won the match yesterday",
        "what was the search for gold like in 1849",
        "i found a new song and it plays with my emotions",
    ):
        assert intents.handle_command(phrase) is None, f"misfired as action: {phrase}"
        reply = pipeline.respond(phrase)
        assert isinstance(reply, str) and reply


# ------------------------------------------------------- nonexistent targets

def test_nonexistent_app_clear_failure(monkeypatch):
    import evo.automation.desktop_agent as da

    class FakeAdapter:
        def launch_app(self, app, reuse_existing=True):
            return {
                "success": False,
                "error": "LAUNCH_VERIFICATION_FAILED: Application 'zanzibarapp' was "
                         "dispatched but no verified visible window appeared within 6.0s.",
            }
        def find_windows_by_app(self, app):
            return []

    monkeypatch.setattr(da, "PYWINAUTO_ADAPTER", FakeAdapter(), raising=False)
    r = intents.handle_command("open zanzibarapp")
    assert r is not None
    assert "couldn't open" in r.text.lower()
    assert "may not be installed" in r.text.lower()


def test_close_nothing_matched_is_polite(monkeypatch):
    import evo.automation.desktop_agent as da

    class FakeAdapter:
        def find_windows_by_app(self, app):
            return []

    monkeypatch.setattr(da, "PYWINAUTO_ADAPTER", FakeAdapter(), raising=False)
    r = intents.handle_command("close nothinghere")
    assert r is not None and "no open windows" in r.text.lower()


# ------------------------------------------------------ rapid sequential cmds

def test_rapid_sequential_no_state_leak(monkeypatch):
    """Back-to-back different-category commands must not leak parameters.
    Uses DDG-fallback mode so each search produces a DISTINCT navigation URL."""
    log = _fake_browser(
        monkeypatch,
        results={"search": "Search page loaded (Loading ...) but no structured results parsed."},
    )
    for text, needle in [
        ("search for cats", "cats"),
        ("open youtube", "youtube.com"),
        ("search for dogs", "dogs"),
        ("search for birds", "birds"),
    ]:
        r = intents.handle_command(text)
        assert r is not None, f"dropped command: {text}"
    urls = log["navigate"]
    assert any("cats" in u for u in urls), urls
    assert any("dogs" in u for u in urls), urls
    assert any("birds" in u for u in urls[-2:]), f"stale params: {urls}"
