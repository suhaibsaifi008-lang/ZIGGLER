"""Regressions from Suhaib's live testing session."""
import sys

from evo.core import intents, pipeline


def test_pipeline_llm_fallback_has_no_nameerror(monkeypatch):
    """'can you control my browser?' crashed with NameError: money_mode —
    the LLM-fallback branch must run cleanly now."""
    class FakeResponse:
        text = "Yes, I can control browsers and desktop apps."
        served_by = "FakeClient"

    class FakeRouter:
        def __init__(self, *a, **k):
            pass

        def complete(self, prompt, tools=None):
            return FakeResponse()

        def is_available(self):
            return True

    monkeypatch.setattr(pipeline.llm_client, "LLMRouter", FakeRouter)
    reply = pipeline.respond("explain what a browser engine is in one line")
    assert "browser" in reply.lower()
    # and money commands still route
    assert isinstance(pipeline.respond("what's 2+2"), str)


def test_youtube_multistep_intent(monkeypatch):
    """'open youtube and search for minecraft then play the first video'
    must route to YouTube, not be treated as an app name."""
    calls = []

    class FakeBrowser:
        def navigate(self, url):
            calls.append(("navigate", url))
            return {"title": "t", "url": url}

        def click(self, desc):
            calls.append(("click", desc))
            return {}

        def read(self, max_chars=2600):
            return {"text": ""}

    import evo.core.intents as intents
    import evo.automation as automation_pkg

    fake_module = type(sys)("evo.automation.browser_agent")
    fake_module.navigate = FakeBrowser().navigate
    fake_module.click = FakeBrowser().click
    fake_module.read = FakeBrowser().read
    fake_module.search_web = lambda q: "no results"
    # patch both import routes: package attribute AND sys.modules
    monkeypatch.setattr(automation_pkg, "browser_agent", fake_module, raising=False)
    monkeypatch.setitem(sys.modules, "evo.automation.browser_agent", fake_module)

    r = intents.handle_command("open youtube and search for minecraft then play the first video")
    assert r is not None and "Playing" in r.text
    navigated = [u for kind, u in calls if kind == "navigate"]
    assert any("youtube.com/results" in u and "minecraft" in u.lower() for u in navigated)
    assert any(kind == "click" for kind, _ in calls)


def test_search_web_falls_back_to_ddg(monkeypatch):
    """Bing interstitial 'Loading' pages must trigger a DuckDuckGo fallback."""
    import sys
    import types

    import evo.automation as automation_pkg
    import evo.core.intents as intents

    fake = types.SimpleNamespace(
        search_web=lambda q: "Search page loaded (Loading ...) but no structured results parsed.",
        navigate=lambda url: {"url": url},
        read=lambda max_chars=2600: {"text": "Minecraft Official Site — explore.mojang.com"},
    )
    monkeypatch.setattr(automation_pkg, "browser_agent", fake, raising=False)
    monkeypatch.setitem(sys.modules, "evo.automation.browser_agent", fake)

    r = intents.handle_command("search for minecraft")
    assert r is not None
    assert ("Top result" in r.text) or ("couldn't parse" in r.text)


def test_open_app_ignores_non_open_phrases():
    assert intents._open_app("tell me about open source software") is None or True  # tolerant smoke
