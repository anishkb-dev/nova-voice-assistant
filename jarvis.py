#!/usr/bin/env python3
"""Jarvis v1 — text assistant on the local Qwen (anish-ai) with tool-calling 'hands'.
Run:  python3 ~/anish-ai/jarvis.py      (needs Ollama running; it usually is)
Quit: type 'exit' or Ctrl-C."""
import subprocess, sys, datetime, os, glob, time, threading, re, ollama

MODEL = "jarvis"

# ---------- the hands (tools) ----------
def get_datetime() -> str:
    return datetime.datetime.now().strftime("%A, %d %B %Y, %I:%M %p")

def open_app(name: str) -> str:
    r = subprocess.run(["open", "-a", name], capture_output=True, text=True)
    return f"Opened {name}." if r.returncode == 0 else f"Couldn't open {name}: {r.stderr.strip()}"

def search_web(query: str) -> str:
    try:
        from ddgs import DDGS
        hits = list(DDGS().text(query, max_results=3))
    except Exception as e:
        return f"Search failed: {e}"
    return "\n".join(f"- {h['title']}: {h['body']}" for h in hits) or "No results."

def run_command(command: str) -> str:
    # human-in-the-loop: never let the model run shell unattended
    print(f"\n  \033[33m⚠  Jarvis wants to run:\033[0m  {command}")
    if input("     Allow this command? [y/N] ").strip().lower() != "y":
        return "The user denied permission to run that command."
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        return ((r.stdout + r.stderr).strip() or "(command ran, no output)")[:2000]
    except subprocess.TimeoutExpired:
        return "Command timed out after 30s."

_player = None            # the running mpv process, if any
_TRACK = "/tmp/jarvis_track"

def _ytdlp() -> str:
    # prefer the pip 'nightly' build (keeps up with YouTube); fall back to brew, then PATH
    for p in (os.path.expanduser("~/Library/Python/3.14/bin/yt-dlp"), "/opt/homebrew/bin/yt-dlp"):
        if os.path.exists(p):
            return p
    return "yt-dlp"

def play_music(query: str) -> str:
    """Download the top YouTube audio result and play it locally (free, no account). Replaces anything playing."""
    global _player
    stop_music()
    for f in glob.glob(_TRACK + ".*"):
        try: os.remove(f)
        except OSError: pass
    try:
        r = subprocess.run(
            [_ytdlp(), "-f", "bestaudio[ext=m4a]/bestaudio", "--no-playlist",
             "-o", _TRACK + ".%(ext)s", "--force-overwrites",
             "--print", "%(title)s", "--no-simulate", f"ytsearch1:{query}"],
            capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return "Timed out fetching the track — check your internet connection."
    files = glob.glob(_TRACK + ".*")
    if not files:
        err = (r.stderr or "").strip().splitlines()
        return f"Couldn't fetch '{query}'. {err[-1][:200] if err else 'No result.'}"
    title = ((r.stdout or "").strip().splitlines() or [query])[0]
    # play a bit below full so the mic can still hear "Hey Jarvis" over the music
    _player = subprocess.Popen(["mpv", "--no-video", "--really-quiet", "--volume=60", files[0]],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Now playing: {title}"

def stop_music() -> str:
    """Stop any music that is currently playing."""
    global _player
    if _player and _player.poll() is None:
        _player.terminate()
        _player = None
        return "Music stopped."
    subprocess.run(["pkill", "-x", "mpv"], capture_output=True)  # backstop for stray players
    return "Nothing was playing."

def set_volume(level: int) -> str:
    """Set the Mac's output volume (0-100)."""
    try:
        lvl = max(0, min(100, int(level)))
    except (TypeError, ValueError):
        return "Please give a volume between 0 and 100."
    subprocess.run(["osascript", "-e", f"set volume output volume {lvl}"], capture_output=True)
    return f"Volume set to {lvl} percent."

def mute(action: str = "toggle") -> str:
    """Mute/unmute all system audio (music, video, everything). action: mute | unmute | toggle."""
    a = (action or "toggle").lower().strip()
    if a == "toggle":
        cur = subprocess.run(["osascript", "-e", "output muted of (get volume settings)"],
                             capture_output=True, text=True).stdout.strip()
        a = "unmute" if cur == "true" else "mute"
    want = "true" if a == "mute" else "false"
    subprocess.run(["osascript", "-e", f"set volume output muted {want}"], capture_output=True)
    return "Muted." if want == "true" else "Unmuted."

_gesture_proc = None
def gesture_control(action: str = "start") -> str:
    """Headless gesture volume: raise an open upright palm to activate, pinch thumb+index to set volume, fist to stop. action: start | stop."""
    global _gesture_proc
    import os
    if (action or "start").lower().strip() == "stop":
        if _gesture_proc and _gesture_proc.poll() is None:
            _gesture_proc.terminate(); _gesture_proc = None
            return "Gesture control off."
        return "Gesture control wasn't running."
    if _gesture_proc and _gesture_proc.poll() is None:
        return "Gesture control is already on."
    script = os.path.join(os.path.dirname(__file__), "gesture_volume.py")
    _gesture_proc = subprocess.Popen([sys.executable, script])
    return "Gesture watcher on — raise an open palm to take control, pinch to set volume, make a fist to release."

def get_weather(location: str = "") -> str:
    """Current weather for a place (or your location if blank). No API key."""
    import urllib.request, urllib.parse
    loc = urllib.parse.quote(location or "")
    try:
        u = f"https://wttr.in/{loc}?format=%l:+%C+%t+(feels+%f),+wind+%w,+humidity+%h"
        return urllib.request.urlopen(u, timeout=10).read().decode().strip()
    except Exception as e:
        return f"Couldn't get the weather: {e}"

def take_screenshot() -> str:
    """Capture the screen to the Desktop."""
    path = os.path.expanduser(f"~/Desktop/jarvis_shot_{datetime.datetime.now():%H%M%S}.png")
    r = subprocess.run(["screencapture", "-x", path], capture_output=True)
    return f"Screenshot saved to {path}." if r.returncode == 0 else "Screenshot failed."

def notify(title: str, message: str = "") -> str:
    """Show a macOS notification banner."""
    t = (title or "J.A.R.V.I.S.").replace('"', "'")
    m = (message or "").replace('"', "'")
    subprocess.run(["osascript", "-e", f'display notification "{m}" with title "{t}"'], capture_output=True)
    return "Notification shown."

def set_reminder(minutes: float, text: str = "") -> str:
    """Remind you after N minutes (speaks + shows a notification)."""
    try:
        secs = max(1, float(minutes)) * 60
    except (TypeError, ValueError):
        return "Please give the number of minutes."
    msg = text or "your reminder, sir"
    def _fire():
        time.sleep(secs)
        subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "Reminder"'], capture_output=True)
        subprocess.run(["say", "-v", "Daniel", f"Reminder, sir: {msg}"], capture_output=True)
    threading.Thread(target=_fire, daemon=True).start()
    return f"I'll remind you in {int(float(minutes))} minute(s): {msg}"

def system_status() -> str:
    """Battery, CPU, and memory at a glance."""
    try:
        import psutil
        b = psutil.sensors_battery()
        bat = f"{round(b.percent)}%{' charging' if b and b.power_plugged else ''}" if b else "n/a"
        return (f"CPU {round(psutil.cpu_percent(interval=0.3))}%, "
                f"memory {round(psutil.virtual_memory().percent)}%, "
                f"disk {round(psutil.disk_usage('/').free/1024**3)}GB free, battery {bat}.")
    except Exception as e:
        return f"Couldn't read system status: {e}"

def create_reminder(text: str, minutes: float = 0) -> str:
    """Add a reminder to the macOS Reminders app (optionally due in N minutes)."""
    t = (text or "reminder").replace('"', "'")
    if minutes and float(minutes) > 0:
        script = (f'set d to (current date) + {int(float(minutes)*60)}\n'
                  f'tell application "Reminders" to make new reminder with properties '
                  f'{{name:"{t}", remind me date:d}}')
        due = f" (in {int(float(minutes))} min)"
    else:
        script = f'tell application "Reminders" to make new reminder with properties {{name:"{t}"}}'
        due = ""
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return f"Reminder added: {text}{due}." if r.returncode == 0 else f"Couldn't add reminder: {r.stderr.strip()[:120]}"

def create_calendar_event(title: str, minutes_from_now: float = 60, duration_min: float = 60) -> str:
    """Add an event to the macOS Calendar, starting N minutes from now."""
    t = (title or "Event").replace('"', "'")
    s = int(float(minutes_from_now) * 60); d = int(float(duration_min) * 60)
    script = (f'set sd to (current date) + {s}\nset ed to sd + {d}\n'
              f'tell application "Calendar" to tell calendar 1 to make new event with properties '
              f'{{summary:"{t}", start date:sd, end date:ed}}')
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return f"Event '{title}' added to your calendar." if r.returncode == 0 else f"Couldn't add event: {r.stderr.strip()[:120]}"

def send_imessage(to: str, message: str) -> str:
    """Send an iMessage to a contact name or phone/email (the app confirms first)."""
    t = (to or "").replace('"', "'"); m = (message or "").replace('"', "'")
    script = (f'tell application "Messages"\n'
              f'set targetService to 1st account whose service type = iMessage\n'
              f'set targetBuddy to participant "{t}" of targetService\n'
              f'send "{m}" to targetBuddy\nend tell')
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return f"Message sent to {to}." if r.returncode == 0 else f"Couldn't send: {r.stderr.strip()[:140]}"

def _lookup_number(name: str) -> str:
    """Find a contact's phone number by name (digits only, for WhatsApp)."""
    script = (f'tell application "Contacts"\n'
              f'set ps to (get value of phones of (1st person whose name contains "{name}"))\n'
              f'return item 1 of ps\nend tell')
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return re.sub(r"[^\d+]", "", r.stdout) if r.returncode == 0 else ""

def send_whatsapp(to: str, message: str) -> str:
    """Send a WhatsApp message. `to` is a phone number (with country code) or a contact name.
    Opens the WhatsApp chat with the text pre-filled and presses send."""
    import urllib.parse
    num = re.sub(r"[^\d+]", "", to or "")
    if not num or len(num) < 7:                       # looks like a name -> look it up in Contacts
        num = _lookup_number(to)
    if not num:
        return f"Couldn't find a WhatsApp number for '{to}', sir. Give me the number with country code."
    num = num.lstrip("+")
    url = "whatsapp://send?phone=%s&text=%s" % (num, urllib.parse.quote(message or ""))
    subprocess.run(["open", url], capture_output=True)
    time.sleep(2.2)                                    # let the chat + pre-filled text load
    subprocess.run(["osascript", "-e",
                    'tell application "WhatsApp" to activate\n'
                    'delay 0.4\n'
                    'tell application "System Events" to key code 36'],  # Return -> send
                   capture_output=True)
    return f"WhatsApp message sent to {to}."

def lock_screen() -> str:
    """Lock the Mac screen immediately."""
    subprocess.run(["pmset", "displaysleepnow"], capture_output=True)
    return "Screen locked, sir."

def set_appearance(mode: str = "toggle") -> str:
    """Switch macOS between dark and light mode. mode: 'dark', 'light', or 'toggle'."""
    m = (mode or "toggle").lower()
    if m == "dark":
        expr = "true"
    elif m == "light":
        expr = "false"
    else:
        expr = "not dark mode"
    subprocess.run(["osascript", "-e",
                    f'tell application "System Events" to tell appearance preferences to set dark mode to {expr}'],
                   capture_output=True)
    return f"Appearance set to {m}."

def get_clipboard() -> str:
    """Read the current clipboard text."""
    r = subprocess.run(["pbpaste"], capture_output=True, text=True)
    return (r.stdout or "").strip()[:1500] or "Clipboard is empty."

def generate_image(prompt: str) -> str:
    """Generate an image from a text prompt (free, via Pollinations/FLUX). Saves to Desktop and opens it."""
    import urllib.parse, urllib.request
    q = urllib.parse.quote((prompt or "abstract art")[:400])
    seed = int(time.time()) % 100000
    url = f"https://image.pollinations.ai/prompt/{q}?width=1024&height=1024&nologo=true&seed={seed}"
    path = os.path.expanduser(f"~/Desktop/jarvis_image_{datetime.datetime.now():%H%M%S}.jpg")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=90).read()
        if len(data) < 1000:
            return "Image generation returned no data, sir."
        with open(path, "wb") as f:
            f.write(data)
        subprocess.run(["open", path], capture_output=True)
        return f"Image generated and saved to {path}."
    except Exception as e:
        return f"Image generation failed: {e}"

def read_file(path: str) -> str:
    """Read a text file's contents (first ~4000 chars)."""
    p = os.path.expanduser((path or "").strip())
    try:
        with open(p, "r", errors="ignore") as f:
            t = f.read()
        return (t[:4000] + ("\n… (truncated)" if len(t) > 4000 else "")) or "(file is empty)"
    except Exception as e:
        return f"Couldn't read {path}: {e}"

def write_file(path: str, content: str) -> str:
    """Create or overwrite a text file with the given content."""
    p = os.path.expanduser((path or "").strip())
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w") as f:
            f.write(content or "")
        return f"Saved {len(content or '')} characters to {path}."
    except Exception as e:
        return f"Couldn't write {path}: {e}"

def list_files(directory: str = "~") -> str:
    """List files in a directory."""
    p = os.path.expanduser((directory or "~").strip())
    try:
        items = sorted(os.listdir(p))
        return ", ".join(items[:60]) or "(empty)"
    except Exception as e:
        return f"Couldn't list {directory}: {e}"

# ---------- IoT (smart room over MQTT) ----------
_IOT_BROKER, _IOT_ROOM = "localhost", "room"
_IOT_DEVICES = {"light", "fan", "plug"}

def iot_control(device: str, action: str) -> str:
    """Turn a smart-room device on/off/toggle: light, fan, plug, or 'all'."""
    import paho.mqtt.client as mqtt
    dev = (device or "").lower().strip()
    act = (action or "").lower().strip()
    dev = {"lights": "light", "lamp": "light", "bulb": "light", "everything": "all"}.get(dev, dev)
    act = {"enable": "on", "start": "on", "disable": "off", "stop": "off"}.get(act, act)
    if dev not in _IOT_DEVICES | {"all"} or act not in {"on", "off", "toggle"}:
        return "I can switch the light, fan, or plug on or off, sir."
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except Exception:
        c = mqtt.Client()
    try:
        c.connect(_IOT_BROKER, 1883, 5)
        for t in (sorted(_IOT_DEVICES) if dev == "all" else [dev]):
            c.publish(f"home/{_IOT_ROOM}/{t}/set", act)
        c.disconnect()
    except Exception as e:
        return f"Couldn't reach the IoT broker (is Mosquitto running?): {e}"
    return ("Everything turned " + act if dev == "all" else dev.capitalize() + " turned " + act) + ", sir."

def ac(command: str) -> str:
    """Control the AC via the HomeMate/Tuya Smart-IR blaster. command e.g. 'on','off','temp 24','mode cool','fan high'."""
    import os, sys
    sys.path.insert(0, os.path.expanduser("~/anish-ai"))
    from ac_control import ac as _ac
    return _ac(command)

def iot_status() -> str:
    """Read the smart room's live sensors and device states over MQTT."""
    import paho.mqtt.client as mqtt, json as _json, time as _time
    data = {}
    def on_msg(c, u, m):
        key = m.topic.split("/")[-1]
        val = m.payload.decode()
        if key == "telemetry":                       # sim sends a JSON blob
            try: data.update(_json.loads(val))
            except Exception: pass
        elif val != "":                              # real ESP32 sends per-topic values
            data[key] = val
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except Exception:
        c = mqtt.Client()
    c.on_message = on_msg
    try:
        c.connect(_IOT_BROKER, 1883, 5)
        c.subscribe(f"home/{_IOT_ROOM}/#")           # telemetry + individual sensor/actuator topics
        c.loop_start(); _time.sleep(2.5); c.loop_stop(); c.disconnect()
    except Exception as e:
        return f"Couldn't reach the IoT broker: {e}"
    if not data:
        return "No telemetry yet, sir — is the room device running?"
    # report only what the hardware actually publishes (real node has no relay -> no light/fan/plug)
    parts = []
    if data.get("temp") is not None:     parts.append(f"{data['temp']} degrees")
    if data.get("humidity") is not None: parts.append(f"{data['humidity']} percent humidity")
    m = data.get("motion")
    if m is not None:                    parts.append("with motion detected" if str(m) not in ("0", "False") else "no motion")
    report = ("The room is " + ", ".join(parts) + ".") if parts else "No sensor readings yet, sir."
    devs = [f"{d} is {data[d]}" for d in ("light", "fan", "plug") if data.get(d) is not None]
    if devs:
        report += " " + "; ".join(devs).capitalize() + "."
    return report

def read_webpage(url: str) -> str:
    """Fetch a web page and return its readable text (first ~2000 chars)."""
    import urllib.request, re as _re
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=12).read().decode("utf-8", "ignore")
    except Exception as e:
        return f"Couldn't fetch the page: {e}"
    html = _re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = _re.sub(r"(?s)<[^>]+>", " ", html)
    text = _re.sub(r"\s+", " ", text).strip()
    return text[:2000] or "No readable text found."

def code(task: str) -> str:
    """Delegate a coding task to the Claude Code agent (`claude -p`) in Nova's workspace.
    For 'write/build/fix/refactor a script|program|app|bug'. Blocks until done, returns a
    short spoken summary; full transcript saved to ~/anish-ai/nova_code/last_task.md.
    Runs with --permission-mode acceptEdits (auto-approves file edits, not arbitrary shell)."""
    import os, subprocess, shutil
    if not shutil.which("claude"):
        return "The Claude Code CLI isn't installed, so I can't build that yet, sir."
    ws = os.path.expanduser("~/anish-ai/nova_code")
    os.makedirs(ws, exist_ok=True)
    try:
        r = subprocess.run(["claude", "-p", task, "--permission-mode", "acceptEdits"],
                           cwd=ws, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return "That task ran past five minutes so I stopped it — try a smaller ask, sir."
    except Exception as e:
        return "Couldn't run Claude Code: %s" % str(e)[:120]
    out = (r.stdout or "").strip() or (r.stderr or "").strip()
    try:
        open(os.path.join(ws, "last_task.md"), "w").write("# %s\n\n%s\n" % (task, out))
    except OSError:
        pass
    if not out:
        return "Done, sir — saved to the nova_code folder."
    return "Done, sir. " + (out[-450:] if len(out) > 450 else out)

def design(prompt: str) -> str:
    """Generate a self-contained HTML design (poster/page/flyer/card) from a description and open it.
    For 'design a ...', 'make a poster/landing page/menu/flyer', 'create a webpage that ...'.
    Uses the router's free 'design' brain, saves to ~/anish-ai/nova_designs/, opens in the browser."""
    import os, re, subprocess, time
    try:
        import router
    except Exception:
        return "My design brain isn't available, sir."
    sysp = ("You are a senior web/graphic designer. Output ONE complete, self-contained HTML document "
            "for the request: a single file starting with <!doctype html>, all CSS in a <style> tag, any "
            "JS inline. No external files, no CDN links, no markdown fences, no commentary — output ONLY "
            "raw HTML. Make it polished, responsive, and striking: a real color palette, strong typography, "
            "thoughtful layout.")
    try:
        r = router.chat("design", [{"role": "system", "content": sysp},
                                   {"role": "user", "content": prompt}],
                        temperature=0.85, max_tokens=4096, timeout=60)
    except Exception as e:
        return "Couldn't reach a design brain: %s" % str(e)[:100]
    html = (r.get("content") or "").strip()
    html = re.sub(r"^```[a-zA-Z]*\n?", "", html)          # strip accidental markdown fences
    html = re.sub(r"\n?```$", "", html).strip()
    if "<" not in html:
        return "The design brain returned nothing usable — try rephrasing, sir."
    if not html.lower().startswith("<!doctype") and "<html" not in html.lower():
        html = "<!doctype html>\n" + html
    ws = os.path.expanduser("~/anish-ai/nova_designs")
    os.makedirs(ws, exist_ok=True)
    slug = (re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:40] or "design")
    path = os.path.join(ws, "%s-%d.html" % (slug, int(time.time())))
    open(path, "w").write(html)
    try:
        subprocess.run(["open", path], check=False)       # macOS: open in default browser
    except Exception:
        pass
    return "Done, sir — I designed that and opened it in your browser. Saved to nova_designs, via %s." % r.get("provider", "?")

FUNCS = {"get_datetime": get_datetime, "open_app": open_app, "search_web": search_web,
         "play_music": play_music, "stop_music": stop_music, "run_command": run_command,
         "set_volume": set_volume, "mute": mute, "get_weather": get_weather, "take_screenshot": take_screenshot,
         "notify": notify, "set_reminder": set_reminder, "system_status": system_status,
         "read_webpage": read_webpage, "create_reminder": create_reminder,
         "create_calendar_event": create_calendar_event, "send_imessage": send_imessage,
         "lock_screen": lock_screen, "set_appearance": set_appearance, "get_clipboard": get_clipboard,
         "send_whatsapp": send_whatsapp, "generate_image": generate_image, "read_file": read_file,
         "write_file": write_file, "list_files": list_files,
         "iot_control": iot_control, "iot_status": iot_status,
         "ac": ac, "gesture_control": gesture_control, "code": code, "design": design}

TOOLS = [
    {"type": "function", "function": {
        "name": "get_datetime", "description": "Get the current local date and time.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "open_app", "description": "Open a macOS application by name, e.g. Safari, Notes, Spotify.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "The app name"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "search_web", "description": "Search the web for current information and return top results.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "The search query"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "play_music", "description": "Play a song, artist, or album by name (streams audio from YouTube). Use this for any 'play ...' music request instead of shell commands.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Song / artist / album to play, e.g. '500 Miles'"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "stop_music", "description": "Stop the music that is currently playing.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "set_volume", "description": "Set the Mac output volume, 0 to 100.",
        "parameters": {"type": "object", "properties": {
            "level": {"type": "integer", "description": "Volume 0-100"}}, "required": ["level"]}}},
    {"type": "function", "function": {
        "name": "mute", "description": "Mute or unmute ALL system audio at once (music, videos, everything). Use for 'mute', 'unmute', 'silence everything'.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["mute", "unmute", "toggle"], "description": "mute, unmute, or toggle (default toggle)"}}}}},
    {"type": "function", "function": {
        "name": "gesture_control", "description": "Turn on/off hands-free gesture volume control (webcam: pinch thumb and index finger to set volume). Use for 'gesture control', 'control volume with my hand'.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["start", "stop"], "description": "start or stop (default start)"}}}}},
    {"type": "function", "function": {
        "name": "get_weather", "description": "Get current weather. Pass a city, or leave blank for the user's location.",
        "parameters": {"type": "object", "properties": {
            "location": {"type": "string", "description": "City name, optional"}}}}},
    {"type": "function", "function": {
        "name": "take_screenshot", "description": "Capture the screen and save it to the Desktop.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "notify", "description": "Show a macOS notification banner.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"}, "message": {"type": "string"}}, "required": ["title"]}}},
    {"type": "function", "function": {
        "name": "set_reminder", "description": "Remind the user after some minutes (speaks and shows a banner).",
        "parameters": {"type": "object", "properties": {
            "minutes": {"type": "number", "description": "Minutes from now"},
            "text": {"type": "string", "description": "What to remind about"}}, "required": ["minutes"]}}},
    {"type": "function", "function": {
        "name": "system_status", "description": "Report battery, CPU, memory, and free disk.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "read_webpage", "description": "Fetch a web page by URL and return its readable text.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "Full URL, e.g. https://..."}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "create_reminder", "description": "Add a persistent reminder to the macOS Reminders app. Optionally due in N minutes. Use for 'remind me to ...' tasks that should persist.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "What to be reminded of"},
            "minutes": {"type": "number", "description": "Minutes from now it's due (0 = no due time)"}}, "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "create_calendar_event", "description": "Add an event to the macOS Calendar. Use for 'schedule ...' or 'add a meeting'.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "Event title"},
            "minutes_from_now": {"type": "number", "description": "When it starts, minutes from now"},
            "duration_min": {"type": "number", "description": "Length in minutes"}}, "required": ["title"]}}},
    {"type": "function", "function": {
        "name": "send_imessage", "description": "Send an iMessage to a contact name or number/email. Use for 'text ...' or 'message ...'.",
        "parameters": {"type": "object", "properties": {
            "to": {"type": "string", "description": "Contact name, phone, or email"},
            "message": {"type": "string", "description": "The message text"}}, "required": ["to", "message"]}}},
    {"type": "function", "function": {
        "name": "send_whatsapp", "description": "Send a WhatsApp message. Use for 'whatsapp ...' or 'message X on whatsapp'.",
        "parameters": {"type": "object", "properties": {
            "to": {"type": "string", "description": "Contact name, or phone number with country code"},
            "message": {"type": "string", "description": "The message text"}}, "required": ["to", "message"]}}},
    {"type": "function", "function": {
        "name": "lock_screen", "description": "Lock the Mac screen / put the display to sleep.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "set_appearance", "description": "Switch macOS dark/light mode.",
        "parameters": {"type": "object", "properties": {
            "mode": {"type": "string", "description": "'dark', 'light', or 'toggle'"}}}}},
    {"type": "function", "function": {
        "name": "get_clipboard", "description": "Read what's currently on the clipboard.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "generate_image", "description": "Generate an image from a text description (AI text-to-image). Use for 'draw ...', 'generate an image of ...', 'create a picture ...'.",
        "parameters": {"type": "object", "properties": {
            "prompt": {"type": "string", "description": "Detailed description of the image to create"}}, "required": ["prompt"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read the contents of a text file. Use when asked about a file's contents or to edit one (read first).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path, e.g. ~/Desktop/notes.txt"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "Create or overwrite a text file with content. Use for 'save this to a file', 'create a file', or after editing.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path to write"},
            "content": {"type": "string", "description": "The full file content"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "list_files", "description": "List files in a directory.",
        "parameters": {"type": "object", "properties": {
            "directory": {"type": "string", "description": "Directory path, default home"}}}}},
    {"type": "function", "function": {
        "name": "iot_control", "description": "Control a smart-room IoT device. Use for 'turn on/off the light/fan/plug', or 'turn everything off'.",
        "parameters": {"type": "object", "properties": {
            "device": {"type": "string", "description": "light, fan, plug, or all"},
            "action": {"type": "string", "description": "on, off, or toggle"}}, "required": ["device", "action"]}}},
    {"type": "function", "function": {
        "name": "ac", "description": "Control the air conditioner (AC) via the smart IR blaster. Use for 'turn on/off the AC', 'set AC to 24', 'AC cool mode', 'AC fan high'.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "e.g. 'on', 'off', 'temp 24', 'mode cool', 'fan high'"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "iot_status", "description": "Read the smart room's live sensors (temperature, humidity, motion) and device states. Use for 'what's the room temperature', 'is anyone in the room', 'room status'.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "remember", "description": "Store a durable fact about the user to recall in future sessions (name, preferences, ongoing projects, anything worth remembering). Use when the user shares something personal or says 'remember'.",
        "parameters": {"type": "object", "properties": {
            "fact": {"type": "string", "description": "The fact to remember, e.g. 'prefers concise answers' or 'is working on a Kaggle competition'"}}, "required": ["fact"]}}},
    {"type": "function", "function": {
        "name": "run_command", "description": "Run any shell command on the Mac (user approves it). Use this for ANY task the other tools don't cover — files, system control, apps, anything.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "The shell command to run"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "code", "description": "Write, build, fix, or refactor code by delegating to the Claude Code agent. Use for 'write a script/program/function', 'build an app/website/CLI/scraper', 'fix this bug', 'refactor ...'. Pass the full task in natural language.",
        "parameters": {"type": "object", "properties": {
            "task": {"type": "string", "description": "The full coding task in natural language, e.g. 'write a Python script that resizes all images in ~/Desktop to 800px wide'"}}, "required": ["task"]}}},
    {"type": "function", "function": {
        "name": "design", "description": "Generate a visual design as a self-contained HTML page and open it. Use for 'design a poster/flyer/landing page/menu/card/resume', 'make a webpage that ...', 'mock up a ...'.",
        "parameters": {"type": "object", "properties": {
            "prompt": {"type": "string", "description": "What to design, in natural language, e.g. 'a minimalist poster for a jazz night on Friday at 8pm'"}}, "required": ["prompt"]}}},
]

# ---------- the loop ----------
def main():
    C, DIM, R = "\033[38;5;44m", "\033[2m", "\033[0m"
    hour = datetime.datetime.now().hour
    part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
    print(f"""{C}
     ◢◤  J.A.R.V.I.S.  ◥◣
   Just A Rather Very Intelligent System{R}
{DIM}   local · offline · at your service   —   type 'exit' to power down{R}
""")
    print(f"{C}J.A.R.V.I.S.:{R} Good {part}, sir. All systems online. How may I be of service?\n")
    messages = []
    while True:
        try:
            user = input("\033[1mYou:\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nJarvis: Goodbye."); return
        if user.lower() in {"exit", "quit", "bye", "/bye"}:
            print("Jarvis: Goodbye."); return
        if not user:
            continue
        messages.append({"role": "user", "content": user})

        # inner loop: keep going until the model answers with no more tool calls
        while True:
            resp = ollama.chat(model=MODEL, messages=messages, tools=TOOLS)
            msg = resp["message"]
            calls = msg.get("tool_calls") or []
            messages.append({"role": "assistant", "content": msg.get("content", ""),
                             "tool_calls": calls})
            if not calls:
                print(f"\033[38;5;44mJ.A.R.V.I.S.:\033[0m {msg.get('content','').strip()}\n")
                break
            for tc in calls:
                fn = tc["function"]["name"]
                args = tc["function"].get("arguments", {}) or {}
                print(f"  \033[90m↳ using {fn}({', '.join(f'{k}={v!r}' for k,v in args.items())})\033[0m")
                try:
                    result = FUNCS[fn](**args) if fn in FUNCS else f"Unknown tool {fn}"
                except Exception as e:
                    result = f"Tool {fn} errored: {e}"
                messages.append({"role": "tool", "content": str(result), "tool_name": fn})

if __name__ == "__main__":
    main()
