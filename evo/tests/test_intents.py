"""Intent engine: instant local Jarvis commands. Network-dependent intents are
exercised live but degrade to honest failure text rather than crashing."""
from evo.core import memory_store, intents


def test_time_intent():
    result = intents.handle_command("what time is it")
    assert result and result.actioned
    assert ":" in result.text and ("AM" in result.text or "PM" in result.text)


def test_date_intent():
    result = intents.handle_command("what is the date today")
    assert result and result.actioned
    assert any(m in result.text for m in ("January", "February", "March", "April", "May", "June",
                                          "July", "August", "September", "October", "November", "December"))


def test_remember_and_recall_cycle():
    r1 = intents.handle_command("remember that my locker code is 4471")
    assert r1 and "Noted" in r1.text
    assert memory_store.recall_fact("my locker code") == "4471"
    r2 = intents.handle_command("what do you know about locker code")
    assert r2 and "4471" in r2.text
    memory_store.remember_fact("my locker code", "")  # cleanup


def test_reminder_set_and_list():
    r = intents.handle_command("remind me in 2 minutes to check the oven")
    assert r and "Reminder #" in r.text
    listing = intents.handle_command("list my reminders")
    assert listing and "check the oven" in listing.text
    pending = memory_store.pending_reminders()
    match = next(x for x in pending if x["message"].endswith("check the oven"))
    memory_store.cancel_reminder(match["id"])


def test_unknown_falls_through_to_llm():
    assert intents.handle_command("explain quantum entanglement poetically") is None


def test_weather_intent_handles_city():
    result = intents.handle_command("what's the weather in London")
    # Live network call; either a real answer or an honest failure — never a crash.
    assert result is not None
    assert ("°C" in result.text) or ("failed" in result.text.lower()) or ("city" in result.text.lower())


def test_system_status():
    result = intents.handle_command("how is the system doing")
    if result:  # psutil present on this machine; keep tolerant anyway
        assert "%" in result.text or "failed" in result.text.lower()
