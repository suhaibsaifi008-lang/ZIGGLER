"""Web test-harness acceptance: endpoints answer correctly on an ephemeral port."""
import json
import threading
import urllib.request

import pytest

from evo.webui.server import ZigglerHandler, ThreadingHTTPServer


@pytest.fixture(scope="module")
def base_url():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ZigglerHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


def _get(path: str, base_url: str):
    with urllib.request.urlopen(base_url + path, timeout=10) as r:
        return r.status, json.loads(r.read())


def _post(path: str, body: dict, base_url: str, timeout: int = 60):
    req = urllib.request.Request(
        base_url + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_index_serves_html(base_url):
    with urllib.request.urlopen(base_url + "/", timeout=10) as r:
        assert r.status == 200
        assert b"ZIGGLER" in r.read()


def test_abilities_enumerates_catalog(base_url):
    status, body = _get("/api/abilities", base_url)
    assert status == 200
    abilities = body["abilities"]
    for module in ("orchestrator", "browser_agent", "desktop_agent", "code_agent", "llm_router"):
        assert module in abilities
    assert body["gateway"]["url"] is not None


def test_models_endpoint_lists_gateway_catalog(base_url):
    status, body = _get("/api/models", base_url)
    assert status == 200
    assert isinstance(body["models"], list)


def test_chat_rejects_empty(base_url):
    status, body = _post("/api/chat", {"message": ""}, base_url)
    assert status == 400


def test_goal_runner_reports_unknown_goal(base_url):
    # Unknown goals engage the LLM planner (Section 2), which can take a while on
    # local models. The endpoint must return a well-formed GoalResult either way.
    status, body = _post("/api/goal", {"goal": "no such goal exists"}, base_url, timeout=240)
    assert status == 200
    assert isinstance(body["success"], bool)
