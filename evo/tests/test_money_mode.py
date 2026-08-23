"""Money mode: lead scanning, scoring, persistence, and command routing."""
import json

from evo.core import memory_store, money_mode


def test_skill_matching_scoring():
    assert money_mode._score("Python Automation Engineer", "build web scrapers", ["python", "web"]) == 2
    assert money_mode._score("Chef", "cook things", ["python"]) == 0


def test_set_and_get_skills(monkeypatch, tmp_path):
    monkeypatch.setattr(memory_store, "_PATH", tmp_path / "memory.json")
    money_mode.set_skills("python, copywriting, canva")
    assert money_mode.get_skills() == ["python", "copywriting", "canva"]


def test_command_routing(monkeypatch, tmp_path):
    monkeypatch.setattr(memory_store, "_PATH", tmp_path / "memory.json")
    r = money_mode.handle_money_command("set my money skills to python, writing")
    assert "Skills saved" in r
    assert money_mode.handle_money_command("what's the weather") is None
    r2 = money_mode.handle_money_command("draft proposal 3")
    assert "money report" in r2.lower()  # no leads yet -> honest guidance


def test_report_with_no_network_is_honest(monkeypatch, tmp_path):
    monkeypatch.setattr(memory_store, "_PATH", tmp_path / "memory.json")

    def dead_fetch(url, timeout=12.0):
        raise OSError("offline")

    monkeypatch.setattr(money_mode, "_fetch", dead_fetch)
    out = money_mode.report()
    assert ("No matching leads" in out) or ("opportunities" in out)
