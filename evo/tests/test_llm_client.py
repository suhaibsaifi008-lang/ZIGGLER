"""Phase B acceptance: LLMRouter fallback behaviour, including the required
mocked rate-limit case. No network access needed — all backends are fakes."""
import pytest

from evo.core.llm_client import (
    LLMError,
    LLMResponse,
    LLMRouter,
    RateLimitError,
)


class FakeOK:
    def __init__(self, name="ok"):
        self.name = name

    def is_available(self):
        return True

    def complete(self, prompt, tools=None):
        return LLMResponse(text=f"{self.name}:{prompt}")


class FakeUnavailable:
    def is_available(self):
        return False

    def complete(self, prompt, tools=None):
        raise AssertionError("complete() must not be called when unavailable")


class FakeRateLimited:
    def __init__(self):
        self.calls = 0

    def is_available(self):
        return True

    def complete(self, prompt, tools=None):
        self.calls += 1
        raise RateLimitError("HTTP 429: rate limit exceeded")


class FakeBroken:
    def is_available(self):
        return True

    def complete(self, prompt, tools=None):
        raise LLMError("connection reset")


def test_router_uses_primary_on_success():
    router = LLMRouter(primary=FakeOK("primary"), fallback=FakeUnavailable())
    result = router.complete("hello")
    assert result.text == "primary:hello"


def test_router_falls_back_when_primary_unavailable():
    router = LLMRouter(primary=FakeUnavailable(), fallback=FakeOK("fallback"))
    result = router.complete("hello")
    assert result.text == "fallback:hello"


def test_router_falls_back_on_rate_limit():
    primary = FakeRateLimited()
    router = LLMRouter(primary=primary, fallback=FakeOK("fallback"))
    result = router.complete("hello")
    assert result.text == "fallback:hello"
    assert primary.calls == 1, "primary must be attempted exactly once before falling back"


def test_router_falls_back_on_generic_error():
    router = LLMRouter(primary=FakeBroken(), fallback=FakeOK("fallback"))
    assert router.complete("hello").text == "fallback:hello"


def test_router_raises_when_all_backends_fail():
    router = LLMRouter(primary=FakeRateLimited(), fallback=FakeUnavailable())
    with pytest.raises(LLMError):
        router.complete("hello")


def test_router_is_available_reflects_backends():
    assert LLMRouter(primary=FakeOK(), fallback=FakeUnavailable()).is_available() is True
    assert LLMRouter(primary=FakeUnavailable(), fallback=FakeOK()).is_available() is True
    assert LLMRouter(primary=FakeUnavailable(), fallback=FakeUnavailable()).is_available() is False


def test_groq_client_maps_http_429_to_rate_limit_error(monkeypatch):
    from evo.core import llm_client as lc

    def fake_urlopen(req, timeout):
        raise lc.urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", hdrs=None, fp=None)

    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
    client = lc.GroqClient(api_key="test-key")
    with pytest.raises(RateLimitError):
        client.complete("hi")
