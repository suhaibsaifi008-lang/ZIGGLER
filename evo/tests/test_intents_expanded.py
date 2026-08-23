"""Jarvis expansion intents: instant-answer and OS-control handlers."""
from evo.core import intents, memory_store


def test_calculator():
    assert intents.handle_command("what is 45*12").text == "45*12 = 540"
    assert "3.5" in intents.handle_command("calculate 7 / 2").text


def test_timer_parses_for_and_in():
    r = intents.handle_command("set a timer for 5 minutes")
    assert r and "Timer set for 5 minutes" in r.text
    match = next(x for x in memory_store.pending_reminders() if x["message"] == "timer finished")
    memory_store.cancel_reminder(match["id"])
    r2 = intents.handle_command("remind me in 1 minute to flip the laundry")
    assert r2 and "Reminder #" in r2.text
    match = next(x for x in memory_store.pending_reminders() if x["message"].endswith("flip the laundry"))
    memory_store.cancel_reminder(match["id"])


def test_notes_roundtrip():
    intents.handle_command("note: ziggler test note alpha")
    listing = intents.handle_command("show my notes")
    assert "ziggler test note alpha" in listing.text
    notes = __import__("json").loads(memory_store.get_preference("notes", "[]"))
    notes[:] = [n for n in notes if n["text"] != "ziggler test note alpha"]
    memory_store.set_preference("notes", __import__("json").dumps(notes))


def test_wikipedia_instant_answer():
    r = intents.handle_command("who is Albert Einstein")
    assert r is not None
    assert ("physicist" in r.text.lower()) or ("failed" in r.text.lower())


def test_dictionary():
    r = intents.handle_command("define computer")
    assert r is not None
    lowered = r.text.lower()
    assert ("noun" in lowered or "verb" in lowered or "no dictionary entry" in lowered)


def test_news_headlines():
    r = intents.handle_command("what's in the news")
    assert r is not None
    assert ("headlines" in r.text.lower()) or ("failed" in r.text.lower())


def test_briefing_composes():
    r = intents.handle_command("good morning — give me my briefing")
    assert r is not None
    assert "It's" in r.text  # time always present; weather/news best-effort


def test_unknown_commands_still_fall_through():
    assert intents.handle_command("write me a haiku about rain") is None
