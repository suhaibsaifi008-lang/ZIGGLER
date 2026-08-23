"""Jarvis-style intent engine: instant local handling of everyday commands.

Order of resolution: regex/rule intents (zero latency, work offline) -> LLM
conversation fallback. Every handler returns a SpeakResult so voice and web
front-ends behave identically.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from evo.core import memory_store


class SpeakResult:
    def __init__(self, text: str, actioned: bool = True, meta: dict | None = None):
        self.text = text
        self.actioned = actioned  # False => caller should fall through to the LLM
        self.meta = meta or {}


# ------------------------------------------------------------------ helpers

def _now() -> _dt.datetime:
    return _dt.datetime.now()


def _parse_duration(text: str) -> tuple[float, str] | None:
    """Extract 'in/for 10 minutes|2 hours|45 seconds' -> (delay_seconds, pretty)."""
    m = re.search(r"(?:in|for)\s+(\d+)\s*(second|minute|hour|sec|min|hr)s?", text.lower())
    if not m:
        return None
    value = int(m.group(1))
    unit = m.group(2)
    factor = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600}[unit]
    delay = value * factor
    return delay, f"{value} {unit}{'s' if value != 1 else ''}"


def _fetch_json(url: str, timeout: float = 8.0) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "ziggler/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ------------------------------------------------------------------ intents

def _time_date(text: str) -> SpeakResult | None:
    t = text.lower()
    if re.search(r"\b(time)\b", t) and "timer" not in t:
        if "date" in t:
            return None
        return SpeakResult(f"It's {_now().strftime('%I:%M %p')}.")
    if "date" in t or "today" in t and "what" in t:
        return SpeakResult(f"Today is {_now().strftime('%A, %d %B %Y')}.")
    return None


def _weather(text: str) -> SpeakResult | None:
    if "weather" not in text.lower():
        return None
    city = memory_store.get_preference("city", "")
    m = re.search(r"weather(?:\s+(?:in|for|at))?\s+([a-zA-Z\s]+)", text.lower())
    if m:
        candidate = m.group(1).strip()
        for stop in ("today", "tomorrow", "now", "please", "like", "outside"):
            candidate = re.sub(rf"\b{stop}\b", "", candidate)
        city = candidate.strip(" ?!") or city
    if not city:
        return SpeakResult("Which city should I use? Say 'set my city to <name>' first.", actioned=True)
    try:
        data = _fetch_json(f"https://wttr.in/{city.replace(' ', '+')}?format=j1")
        current = data["current_condition"][0]
        desc = current["weatherDesc"][0]["value"]
        answer = (
            f"{city.title()}: {desc}, {current['temp_C']}°C "
            f"(feels like {current['FeelsLikeC']}°C), humidity {current['humidity']}%, "
            f"wind {current['windspeedKmph']} km/h."
        )
        return SpeakResult(answer, meta={"city": city})
    except Exception as exc:
        return SpeakResult(f"Weather lookup failed: {exc}")


def _remember(text: str) -> SpeakResult | None:
    m = re.search(r"remember(?: that)? (.+)", text, re.IGNORECASE)
    if not m:
        return None
    fact = m.group(1).strip()
    if "=" in fact:
        key, value = fact.split("=", 1)
    elif " is " in fact.lower():
        parts = re.split(r" is ", fact, maxsplit=1, flags=re.IGNORECASE)
        key, value = parts[0], parts[1]
    else:
        key, value = fact[:40], fact
    memory_store.remember_fact(key.strip(), value.strip())
    return SpeakResult(f"Noted. {key.strip()} = {value.strip()}")


def _recall(text: str) -> SpeakResult | None:
    m = re.search(r"(?:what do you know about|what did i say about|recall)\s+(.+)", text, re.IGNORECASE)
    if not m:
        return None
    query = m.group(1).strip(" ?!")
    hits = memory_store.search_facts(query)
    if not hits:
        return SpeakResult(f"I don't have anything stored about '{query}'.")
    best_key = min(hits, key=lambda k: len(k))
    return SpeakResult(f"{best_key}: {hits[best_key]}")


def _remind(text: str) -> SpeakResult | None:
    t = text.lower()
    if "remind me" not in t and "set a reminder" not in t and "wake me" not in t:
        return None
    parsed = _parse_duration(t)
    if not parsed:
        return SpeakResult("Tell me a delay, e.g. 'remind me in 20 minutes to stretch'.")
    delay, pretty = parsed
    m = re.search(r"to (.+)$", t)
    task = m.group(1) if m else "your reminder"
    rid = memory_store.add_reminder(task, time.time() + delay)
    return SpeakResult(f"Reminder #{rid} set for in {pretty}: {task}.", meta={"id": rid})


def _list_reminders(text: str) -> SpeakResult | None:
    if not re.search(r"(my )?(reminders|pending)", text.lower()):
        return None
    pending = memory_store.pending_reminders()
    if not pending:
        return SpeakResult("No pending reminders.")
    lines = [f"#{r['id']} — {r['message']}" for r in pending[:6]]
    return SpeakResult(f"{len(pending)} pending. " + "; ".join(lines))


def _system_status(text: str) -> SpeakResult | None:
    if not re.search(r"\b(battery|cpu|system status|how are you doing|memory usage)\b", text.lower()):
        return None
    try:
        import psutil

        battery = psutil.sensors_battery()
        cpu = psutil.cpu_percent(interval=0.4)
        ram = psutil.virtual_memory()
        parts = [f"CPU at {cpu}%", f"RAM {ram.percent}% used"]
        if battery:
            plug = "charging" if battery.power_plugged else "on battery"
            parts.append(f"battery {round(battery.percent)}% ({plug})")
        return SpeakResult(", ".join(parts) + ".")
    except Exception as exc:
        return SpeakResult(f"System check failed: {exc}")


def _screenshot(text: str) -> SpeakResult | None:
    if "screenshot" not in text.lower():
        return None
    from evo.automation.desktop_agent import PYWINAUTO_ADAPTER
    import ctypes

    user32 = ctypes.windll.user32
    out_dir = os.path.join(os.environ.get("USERPROFILE", "."), "Pictures", "Ziggler")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"screenshot_{int(time.time())}.png")
    # PrintScreen-free capture via Playwright is browser-only; use PowerShell here.
    script = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
        "$bmp=New-Object Drawing.Bitmap $b.Width,$b.Height;"
        "$g=[Drawing.Graphics]::FromImage($bmp);"
        f"$g.CopyFromScreen(0,0,0,0,$bmp.Size);"
        f"$bmp.Save('{path}')"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=15)
    ok = os.path.exists(path)
    return SpeakResult(f"Screenshot saved to {path}" if ok else "Screenshot failed.")


def _volume(text: str) -> SpeakResult | None:
    t = text.lower()
    m = re.search(r"(?:set\s+)?volume(?: to)? (\d{1,3})\b", t)
    if "mute" in t:
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"], capture_output=True)
        return SpeakResult("Muted.")
    if not m:
        return None
    level = max(0, min(100, int(m.group(1))))
    ps = (
        "$o=New-Object -ComObject WScript.Shell; 50..0 | ForEach-Object { $o.SendKeys([char]174) };"
        f"(1..{max(1, level // 2)}) | ForEach-Object {{ $o.SendKeys([char]175) }}"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=15)
    return SpeakResult(f"Volume set to roughly {level} percent.")


def _open_app(text: str) -> SpeakResult | None:
    m = re.search(r"\b(?:open|launch|start)\s+([a-z0-9 ]+)", text.lower())
    if not m:
        return None
    app = m.group(1).strip()
    blocked = ("browser", "the")  # 'open browser' handled by generic launch too — fine
    app_clean = app.replace("the ", "").strip()
    if not app_clean:
        return None
    from evo.automation.desktop_agent import PYWINAUTO_ADAPTER

    result = PYWINAUTO_ADAPTER.launch_app(app_clean, reuse_existing=True)
    if result.get("success"):
        return SpeakResult(f"{app_clean.title()} is open.")
    return SpeakResult(f"I couldn't open {app_clean}: {result.get('error', 'unknown reason')}")


def _search_web(text: str) -> SpeakResult | None:
    m = re.search(r"(?:search(?: the web)?(?: for)?|google)\s+(.+)", text, re.IGNORECASE)
    if not m:
        return None
    query = m.group(1).strip(" ?!")
    from evo.automation import browser_agent

    summary = browser_agent.search_web(query)
    first_line = next((ln for ln in summary.splitlines() if ln.strip()), "no results parsed")
    return SpeakResult(
        f"Top result for {query}: {first_line.strip()} Full page is open in the automation browser.",
        meta={"query": query},
    )


def _play_music(text: str) -> SpeakResult | None:
    m = re.search(r"(?:play|put on)\s+(.+?)(?:\s+on youtube)?[.?!]?$", text, re.IGNORECASE)
    if not m:
        return None
    what = m.group(1).strip(" ?!")
    from evo.automation import browser_agent

    browser_agent.navigate(f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(what)}")
    try:
        from evo.automation import browser_agent as ba

        ba.click("ytd-video-renderer a#video-title")
        return SpeakResult(f"Playing {what}.")
    except LookupError:
        return SpeakResult(f"Search results for {what} are open — pick one.")


def _set_city(text: str) -> SpeakResult | None:
    m = re.search(r"(?:set )?(?:my )?city to ([a-zA-Z\s]+)", text.lower())
    if not m:
        return None
    city = m.group(1).strip(" ?!")
    memory_store.set_preference("city", city)
    return SpeakResult(f"City saved as {city.title()}.")


# ------------------------------------------------- Jarvis expansion handlers

def _calc(text: str) -> SpeakResult | None:
    m = re.search(r"(?:calculate|what(?:'s| is))\s+([\d\s+\-*/().%]+)\??$", text.strip())
    if not m or not re.search(r"\d[\s]*[+\-*/%]", m.group(1)):
        return None
    expr = m.group(1).strip()
    if not re.fullmatch(r"[\d\s+\-*/().%]+", expr):
        return None
    try:
        value = eval(expr, {"__builtins__": {}}, {})  # regex-gated arithmetic only
    except Exception:
        return SpeakResult("I couldn't evaluate that expression.")
    pretty = int(value) if float(value).is_integer() else round(value, 6)
    return SpeakResult(f"{expr} = {pretty}")


def _wiki(text: str) -> SpeakResult | None:
    m = re.search(r"(?:who|what)(?:'s| is| are)?\s+(?:the )?(.+?)[?.!]?$", text.strip(), re.IGNORECASE)
    if not m or not re.search(r"\b(who|what)\b", text, re.IGNORECASE):
        return None
    subject = m.group(1).strip()
    if len(subject.split()) > 8:
        return None
    try:
        data = _fetch_json(
            "https://en.wikipedia.org/api/rest_v1/page/summary/"
            + urllib.parse.quote(subject.replace(" ", "_"))
        )
        extract = data.get("extract")
        if not extract:
            return None
        sentences = re.split(r"(?<=[.!?]) ", extract)
        return SpeakResult(" ".join(sentences[:2]), meta={"source": data.get("content_urls", {}).get("desktop", {}).get("page", "")})
    except Exception:
        return None  # fall through to LLM for open questions


def _define(text: str) -> SpeakResult | None:
    m = re.search(r"(?:define|definition of|meaning of)\s+([a-zA-Z-]+)", text.lower())
    if not m:
        return None
    word = m.group(1)
    try:
        data = _fetch_json(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}")
        first = data[0]
        meaning_block = first["meanings"][0]
        definition = meaning_block["definitions"][0]["definition"]
        return SpeakResult(f"{word} ({meaning_block['partOfSpeech']}): {definition}")
    except Exception as exc:
        return SpeakResult(f"No dictionary entry found for '{word}' ({exc}).")


def _news(text: str) -> SpeakResult | None:
    if not re.search(r"\bnews\b|\bheadlines\b", text.lower()):
        return None
    import xml.etree.ElementTree as ET

    try:
        req = urllib.request.Request(
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            headers={"User-Agent": "ziggler/0.1"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            root = ET.fromstring(resp.read())
        titles = [item.findtext("title") for item in root.iter("item")][:5]
        if not titles:
            return SpeakResult("No headlines parsed from the feed.")
        return SpeakResult("Top world headlines: " + " · ".join(titles))
    except Exception as exc:
        return SpeakResult(f"News fetch failed: {exc}")


def _briefing(text: str) -> SpeakResult | None:
    if not re.search(r"\b(briefing|good morning|good evening|catch me up|status report)\b", text.lower()):
        return None
    parts = [f"It's {_now().strftime('%I:%M %p on %A')}."]
    weather = _weather(f"weather in {memory_store.get_preference('city', 'London')}")
    if weather and "°C" in weather.text:
        parts.append(weather.text)
    pending = memory_store.pending_reminders()
    if pending:
        parts.append(f"You have {len(pending)} reminder(s): " + "; ".join(r["message"] for r in pending[:3]))
    try:
        from evo.core import money_mode

        leads = money_mode.current_leads()
        if leads:
            parts.append(f"Money mode has {len(leads)} saved leads — say 'money report' to see them.")
    except Exception:
        pass
    news = _news("headlines")
    if news and "failed" not in news.text.lower():
        parts.append(news.text[:300])
    try:
        import psutil

        battery = psutil.sensors_battery()
        if battery and not battery.power_plugged:
            parts.append(f"Battery at {round(battery.percent)} percent.")
    except Exception:
        pass
    return SpeakResult(" ".join(parts))


def _timer(text: str) -> SpeakResult | None:
    t = text.lower()
    if "timer" not in t:
        return None
    parsed = _parse_duration(t)
    if not parsed:
        return SpeakResult("How long? e.g. 'set a timer for 5 minutes'.")
    delay, pretty = parsed
    memory_store.add_reminder("timer finished", time.time() + delay)
    return SpeakTimer(delay, pretty)


def _clipboard(text: str) -> SpeakResult | None:
    t = text.lower()
    if not ("clipboard" in t):
        return None
    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    if re.search(r"(copy|put|set) .*clipboard|clipboard (this|it)", t) or re.search(r"copy to clipboard", t):
        payload = re.sub(r"^.*?(copy|put|set)\s*(this |that |it )?(to |on )?(the )?clipboard\s*[:]?\s*", "", text, flags=re.IGNORECASE)
        if not payload:
            return SpeakResult("What should I copy to the clipboard?")
        ok = ctypes.windll.user32.OpenClipboard(None)
        if ok:
            try:
                ctypes.windll.user32.EmptyClipboard()
                data = (ctypes.c_wchar_p * (len(payload) + 1))(payload)
                ctypes.windll.kernel32.GlobalAlloc.restype = ctypes.c_void_p
                handle = ctypes.windll.kernel32.GlobalAlloc(0x2002, ctypes.sizeof(data))
                target = ctypes.windll.kernel32.GlobalLock(handle)
                ctypes.memmove(target, data, ctypes.sizeof(data))
                kernel32.GlobalUnlock(target)
                ctypes.windll.user32.SetClipboardData(13, handle)
            finally:
                ctypes.windll.user32.CloseClipboard()
            return SpeakResult("Copied to clipboard.")
        return SpeakResult("Clipboard was busy.")
    if "read" in t or "what's on" in t or "what is on" in t:
        from evo.automation.desktop_agent import get_clipboard_text

        content = get_clipboard_text()[:400]
        return SpeakResult(f"Clipboard says: {content}" if content else "The clipboard is empty.")
    return None


def _media_keys(text: str) -> SpeakResult | None:
    t = text.lower()
    keys = [
        (r"\bnext (song|track)\b|\bskip\b", 0xB0, "Next track"),
        (r"\b(previous|last) (song|track)\b", 0xB1, "Previous track"),
        (r"\bstop (the )?music\b", 0xB2, "Media stopped"),
        (r"\b(pause|resume)( the)?( music| song| video)?\b", 0xB3, "Play/pause toggled"),
    ]
    match = next(((code, label) for pattern, code, label in keys if re.search(pattern, t)), None)
    if match is None:
        return None
    code, label = match
    ps = f"(New-Object -ComObject WScript.Shell).SendKeys([char]{176 + (code - 176)})"
    # SendKeys takes the char code directly; VK_MEDIA codes map to [char]176..179.
    ps = f"(New-Object -ComObject WScript.Shell).SendKeys([char]{code})"
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=10)
    return SpeakResult(label + ".")


def _brightness(text: str) -> SpeakResult | None:
    m = re.search(r"brightness (?:to )?(\d{1,3})\b", text.lower())
    if not m:
        return None
    level = max(0, min(100, int(m.group(1))))
    ps = (
        "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
        f".WmiSetBrightness(1,{level})"
    )
    proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=12)
    if proc.returncode == 0:
        return SpeakResult(f"Brightness set to {level} percent.")
    return SpeakResult("Brightness control isn't supported on this display.")


def _maps(text: str) -> SpeakResult | None:
    m = re.search(r"(?:directions to|navigate to|route to|map of)\s+(.+)", text, re.IGNORECASE)
    if not m:
        return None
    place = m.group(1).strip(" ?!")
    from evo.automation import browser_agent

    browser_agent.navigate(f"https://www.google.com/maps/search/{urllib.parse.quote_plus(place)}")
    return SpeakResult(f"Map for {place} is open.")


def _summarize(text: str) -> SpeakResult | None:
    m = re.search(r"(?:summarize|summarise|tldr|summary of)\s+(\S+://\S+)", text, re.IGNORECASE)
    if not m:
        return None
    url = m.group(1)
    from evo.automation import browser_agent

    page = browser_agent.navigate(url)
    body = (page.get("preview") or "")[:1200]
    if not body:
        return SpeakResult("I opened it but couldn't extract readable text.")
    try:
        from evo.core.llm_client import LLMRouter

        summary = LLMRouter().complete(f"Summarize in 2 sentences:\n{body}").text.strip()
    except Exception:
        summary = body[:220]
    return SpeakResult(summary)


def _close_app(text: str) -> SpeakResult | None:
    m = re.search(r"\b(?:close|kill|quit)\s+([a-z0-9 ]+)", text.lower())
    if not m or any(word in m.group(1) for word in ("window", "tab")):
        return None
    app = m.group(1).replace("the ", "").strip()
    if not app:
        return None
    from evo.automation.desktop_agent import PYWINAUTO_ADAPTER

    matches = PYWINAUTO_ADAPTER.find_windows_by_app(app)
    if not matches:
        return SpeakResult(f"No open windows matching '{app}'.")
    closed = 0
    for w in matches[:4]:
        if PYWINAUTO_ADAPTER.close_window(w["hwnd"]).get("success"):
            closed += 1
    return SpeakResult(f"Closed {closed} window(s) matching '{app}'.")


def _find_file(text: str) -> SpeakResult | None:
    m = re.search(r"\b(?:find|locate)\s+(?:the )?(?:file|document|pdf|photo) called?\s+(.+)", text, re.IGNORECASE) or \
        re.search(r"\bfind\s+(?:file\s+)?(.+)", text, re.IGNORECASE)
    if not m:
        return None
    needle = m.group(1).strip(" ?!").lower()
    roots = [Path.home() / "Desktop", Path.home() / "Documents", Path.home() / "Downloads"]
    hits: list[Path] = []
    for root in roots:
        if root.exists():
            for p in root.rglob("*"):
                if p.is_file() and needle in p.name.lower():
                    hits.append(p)
                if len(hits) >= 5:
                    break
        if hits:
            break
    if not hits:
        return SpeakResult(f"No files named '*{needle}*' in Desktop/Documents/Downloads.")
    best = hits[0]
    if best.suffix.lower() == ".txt":
        os.startfile(str(best))  # noqa: S606
    else:
        subprocess.Popen(["explorer.exe", "/select,", str(best)])
    return SpeakResult(f"Found: {best}. Opening its folder.", meta={"path": str(best)})


def _notes(text: str) -> SpeakResult | None:
    t = text.lower()
    m = re.search(r"^(?:make a note|note|note down|add (?:a )?(?:note|todo))[,:]?\s*(.+)$", text, re.IGNORECASE)
    if m:
        note = m.group(1).strip()
        notes = json.loads(memory_store.get_preference("notes", "[]"))
        notes.append({"text": note, "at": time.time()})
        memory_store.set_preference("notes", json.dumps(notes[-100:], ensure_ascii=False))
        return SpeakResult(f"Noted: {note}")
    if "show my notes" in t or "my notes" in t or "show todos" in t or "my todos" in t:
        notes = json.loads(memory_store.get_preference("notes", "[]"))
        if not notes:
            return SpeakResult("You have no saved notes.")
        lines = [n["text"] for n in notes[-5:]]
        return SpeakResult(f"Your last {len(lines)} notes: " + " | ".join(lines))
    return None


def _lock_pc(text: str) -> SpeakResult | None:
    if re.search(r"\block\b.*\b(pc|computer|screen|workstation)\b|\block my (pc|computer)\b", text.lower()):
        ctypes_windll = __import__("ctypes").windll
        ctypes_windll.user32.LockWorkStation()
        return SpeakResult("Locking now.")
    return None


class SpeakTimer(SpeakResult):
    """Timer confirmation that also announces itself when it fires later."""

    def __init__(self, delay: float, pretty: str):
        super().__init__(f"Timer set for {pretty}.")
        self.delay = delay


_HANDLERS = [
    _time_date,
    _weather,
    _remember,
    _recall,
    _remind,
    _timer,
    _list_reminders,
    _briefing,
    _news,
    _calc,
    _wiki,
    _define,
    _system_status,
    _screenshot,
    _volume,
    _brightness,
    _media_keys,
    _clipboard,
    _notes,
    _set_city,
    _close_app,
    _open_app,
    _search_web,
    _maps,
    _summarize,
    _find_file,
    _lock_pc,
    _play_music,
]


def handle_command(text: str) -> SpeakResult | None:
    """Return a SpeakResult when a rule-based intent matched, else None."""
    cleaned = (text or "").strip()
    if cleaned.lower().startswith(("hey ziggler", "ziggler")):
        cleaned = re.sub(r"^(hey )?ziggler[,!]?\s*", "", cleaned, flags=re.IGNORECASE)
    for handler in _HANDLERS:
        try:
            result = handler(cleaned)
        except Exception as exc:
            result = SpeakResult(f"That command failed: {exc}")
        if result:
            return result
    return None
