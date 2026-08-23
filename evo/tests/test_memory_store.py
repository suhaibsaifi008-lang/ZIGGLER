"""memory_store: flat-JSON persistence contract."""
from evo.core import memory_store


def test_fact_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_store, "_PATH", tmp_path / "memory.json")
    memory_store.remember_fact("sister's birthday", "March 3rd")
    assert memory_store.recall_fact("SISTER'S Birthday") == "March 3rd"
    hits = memory_store.search_facts("birthday")
    assert any("March 3rd" in v for v in hits.values())


def test_history_trims(monkeypatch, tmp_path):
    monkeypatch.setattr(memory_store, "_PATH", tmp_path / "memory.json")
    for i in range(250):
        memory_store.add_message("user", f"msg {i}")
    history = memory_store.recent_history(300)
    assert len(history) <= 200
    assert history[-1]["content"] == "msg 249"


def test_reminder_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(memory_store, "_PATH", tmp_path / "memory.json")
    rid = memory_store.add_reminder("call back", due_ts=1.0)  # already due
    assert rid == 1
    due = memory_store.due_reminders()
    assert len(due) == 1 and due[0]["message"] == "call back"
    # marked done after surfacing
    assert memory_store.pending_reminders() == []


def test_preferences(monkeypatch, tmp_path):
    monkeypatch.setattr(memory_store, "_PATH", tmp_path / "memory.json")
    memory_store.set_preference("city", "Delhi")
    assert memory_store.get_preference("city") == "Delhi"
    assert memory_store.get_preference("missing", "fallback") == "fallback"
