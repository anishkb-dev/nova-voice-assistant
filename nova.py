#!/usr/bin/env python3
"""Nova v1 — text assistant on the local Qwen (anish-ai) with tool-calling 'hands'.
Run:  python3 ~/anish-ai/nova.py      (needs Ollama running; it usually is)
Quit: type 'exit' or Ctrl-C."""
import subprocess, sys, json, datetime, os, glob, time, threading, re, shutil, ollama

MODEL = "nova"

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
    print(f"\n  \033[33m⚠  Nova wants to run:\033[0m  {command}")
    if input("     Allow this command? [y/N] ").strip().lower() != "y":
        return "The user denied permission to run that command."
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        return ((r.stdout + r.stderr).strip() or "(command ran, no output)")[:2000]
    except subprocess.TimeoutExpired:
        return "Command timed out after 30s."

_player = None            # the running mpv process, if any
_TRACK = "/tmp/nova_track"

def _ytdlp() -> str:
    # prefer the pip 'nightly' build (keeps up with YouTube); fall back to brew, then PATH
    for p in (os.path.expanduser("~/Library/Python/3.14/bin/yt-dlp"), "/opt/homebrew/bin/yt-dlp",
              os.path.join(os.path.dirname(sys.executable), "yt-dlp")):   # last = venv (Intel hub, no brew)
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
    # play a bit below full so the mic can still hear "Hey Nova" over the music
    cmd = (["mpv", "--no-video", "--really-quiet", "--volume=60", files[0]] if shutil.which("mpv")
           else ["afplay", "-v", "0.6", files[0]])          # hub has no Homebrew -> built-in afplay
    _player = subprocess.Popen(cmd,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Now playing: {title}"

def music_playing() -> bool:
    return bool(_player and _player.poll() is None) or \
        subprocess.run(["pgrep", "-x", "mpv"], capture_output=True).returncode == 0

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
    """Hub webcam presence watcher (cam_presence.py) on/off. Name kept from the old gesture-volume feature. action: start | stop."""
    global _gesture_proc
    import os
    if not IS_HUB:                                    # the webcam is on the hub -> it runs gestures
        try:
            _hub_send("gestures", (action or "start").lower().strip())
            return "Room camera %s, sir." % ("off" if "stop" in (action or "") else "on")
        except Exception as e:
            return "Couldn't reach the hub for gestures: %s" % str(e)[:60]
    if (action or "start").lower().strip() == "stop":
        if _gesture_proc and _gesture_proc.poll() is None:
            _gesture_proc.terminate(); _gesture_proc = None
            return "Gesture control off."   # nova_app._welcome_if_owner matches this prefix
        return "Gesture control wasn't running."
    if _gesture_proc and _gesture_proc.poll() is None:
        return "Gesture control is already on."
    script = os.path.join(os.path.dirname(__file__), "cam_presence.py")
    _gesture_proc = subprocess.Popen([sys.executable, script])
    return "Room camera on (presence)."

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
    path = os.path.expanduser(f"~/Desktop/nova_shot_{datetime.datetime.now():%H%M%S}.png")
    r = subprocess.run(["screencapture", "-x", path], capture_output=True)
    return f"Screenshot saved to {path}." if r.returncode == 0 else "Screenshot failed."

def notify(title: str, message: str = "") -> str:
    """Show a macOS notification banner."""
    t = (title or "J.A.R.V.I.S.").replace('"', "'")
    m = (message or "").replace('"', "'")
    subprocess.run(["osascript", "-e", f'display notification "{m}" with title "{t}"'], capture_output=True)
    return "Notification shown."

SPEAK = None   # nova_app sets this to its speak() -> reminders talk as Daniel on the room speaker

def _remind_line(msg):
    """Say it like a butler who remembered ('Sir, it's time to drink some water.'), not read it back.
    Fast Groq model; falls back to a fixed line if offline."""
    try:
        from openai import OpenAI
        key = open(os.path.expanduser("~/anish-ai/.groq_key")).read().strip()
        r = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=key, timeout=6, max_retries=0).chat.completions.create(
            model="openai/gpt-oss-20b", extra_body={"reasoning_effort": "low"}, temperature=0.7, messages=[
                {"role": "system", "content": "You are Nova, a warm, polite British butler. Address the user as 'sir'."},
                {"role": "user", "content": "Earlier I asked you to remind me about: \"%s\". It's time now. Remind me in ONE short, "
                 "natural spoken sentence, as if you remembered it yourself (e.g. 'drink water' -> 'Sir, it's time to drink some "
                 "water.'). Only the sentence." % msg}])
        line = (r.choices[0].message.content or "").strip().strip('"')
        if 5 < len(line) < 200:
            return line
    except Exception:
        pass
    return "Pardon me, sir. A reminder: %s." % msg.rstrip(". ")

def _speak_reminder(msg):
    text = _remind_line(msg)
    if SPEAK:
        try: SPEAK(text); return
        except Exception: pass
    subprocess.run(["say", "-v", "Daniel", text], capture_output=True)   # no app running -> Mac voice

_REM_F = os.path.expanduser("~/anish-ai/.reminders.json")   # pending timed reminders; survive restarts
_REM_LOCK = threading.Lock()

def _rem_edit(fn):
    with _REM_LOCK:
        try: rems = json.load(open(_REM_F))
        except Exception: rems = []
        rems = fn(rems)
        json.dump(rems, open(_REM_F, "w"))
        return rems

def _schedule(due, msg, banner=True):
    """Fire at epoch `due` (late ones fire right away), then drop it from the file."""
    def _fire():
        time.sleep(max(0, due - time.time()))
        if banner:
            subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "Reminder"'], capture_output=True)
        _speak_reminder(msg)
        _rem_edit(lambda r: [x for x in r if (x["due"], x["msg"]) != (due, msg)])
    threading.Thread(target=_fire, daemon=True).start()

def _add_reminder(secs, msg, banner=True):
    due = round(time.time() + secs, 1)
    _rem_edit(lambda r: r + [{"due": due, "msg": msg, "banner": banner}])
    _schedule(due, msg, banner)

def resume_reminders():
    """Called once at startup: re-arm reminders saved before a restart."""
    for x in _rem_edit(lambda r: r):
        _schedule(x["due"], x["msg"], x.get("banner", True))

def set_reminder(minutes: float, text: str = "") -> str:
    """Remind you after N minutes (speaks + shows a notification)."""
    try:
        secs = max(1, float(minutes)) * 60
    except (TypeError, ValueError):
        return "Please give the number of minutes."
    msg = text or "your reminder, sir"
    _add_reminder(secs, msg)
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
    if minutes and float(minutes) > 0:              # the Reminders app only pings silently -> Nova says it too
        _add_reminder(float(minutes) * 60, text or "your reminder", banner=False)
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
    path = os.path.expanduser(f"~/Desktop/nova_image_{datetime.datetime.now():%H%M%S}.jpg")
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
import socket
IS_HUB = socket.gethostname().split(".")[0] == "nova-hub"   # the always-on old Mac drives the room
_IOT_BROKER = os.environ.get("NOVA_BROKER") or ("localhost" if IS_HUB else "nova-hub.local")

def mqtt_client(**kw):
    """paho client signed in as "nova" (broker refuses hub/mac topics to anonymous clients)."""
    import paho.mqtt.client as mqtt
    try: c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, **kw)
    except AttributeError: c = mqtt.Client(**kw)
    c.username_pw_set("nova", open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".mqtt_key")).read().strip())
    return c
_IOT_ROOM = "room"

def _hub_send(what, payload):
    """Ask the hub to do something only it can (BLE strip, pause automations). Fire-and-forget."""
    import paho.mqtt.client as mqtt
    c = mqtt_client()
    _pub(c, [("home/hub/" + what, payload if isinstance(payload, bytes) else str(payload))])   # bytes = audio

def _pub(c, msgs):
    """Connect, publish each (topic, payload) with qos1 and wait for the broker's ack, then hang up.
    Fire-and-hang-up without the network loop got silently dropped by amqtt on the hub."""
    c.connect(_IOT_BROKER, 1883, 5)
    c.loop_start()
    try:
        for t, p in msgs:
            c.publish(t, p, qos=1).wait_for_publish(3)
    finally:
        c.disconnect(); c.loop_stop()
_IOT_DEVICES = {"fan", "plug"}   # relays. "light" = the WiZ bulb (wiz.py); relay K1's old LED strip is dead (2026-11-10)

def iot_control(device: str, action: str) -> str:
    """Turn a smart-room device on/off/toggle: light, fan, plug, or 'all'."""
    import paho.mqtt.client as mqtt
    dev = (device or "").lower().strip()
    act = (action or "").lower().strip()
    dev = {"lights": "light", "lamp": "light", "bulb": "light", "everything": "all"}.get(dev, dev)
    act = {"enable": "on", "start": "on", "disable": "off", "stop": "off"}.get(act, act)
    if dev not in _IOT_DEVICES | {"all", "light"} or act not in {"on", "off", "toggle"}:
        return "I can switch the light, fan, or plug on or off, sir."
    if dev in ("light", "all"):
        import wiz
        if act == "toggle": act = "off" if wiz.state() == "on" else "on"
        said = wiz.bulb(act)
        if dev == "light": return ("Light turned " + act + ", sir.") if said.startswith("Bulb") else said
    c = mqtt_client()
    try:
        _pub(c, [(f"home/{_IOT_ROOM}/{t}/set", act) for t in (sorted(_IOT_DEVICES) if dev == "all" else [dev])])
    except Exception as e:
        return f"Couldn't reach the IoT broker (is Mosquitto running?): {e}"
    return ("Everything turned " + act if dev == "all" else dev.capitalize() + " turned " + act) + ", sir."

# ---------- RC crawler (drive over MQTT: home/car/{throttle,steer}) ----------
def drive(command: str) -> str:
    """Drive the RC crawler: forward, back, stop, left, right, center."""
    import paho.mqtt.client as mqtt
    cmd = (command or "").lower().strip()
    thr = {"forward": "forward", "ahead": "forward", "go": "forward", "front": "forward",
           "back": "back", "backward": "back", "reverse": "back",
           "stop": "stop", "halt": "stop", "brake": "stop"}
    strn = {"left": "left", "right": "right",
            "center": "center", "centre": "center", "straight": "center"}
    msgs = []
    if cmd in thr:
        msgs.append(("throttle", thr[cmd]))
        if thr[cmd] == "stop":
            msgs.append(("steer", "center"))          # a full stop also centres the wheels
    elif cmd in strn:
        msgs.append(("steer", strn[cmd]))
    else:
        return "Say forward, back, stop, left, right, or center, sir."
    c = mqtt_client()
    try:
        c.connect(_IOT_BROKER, 1883, 5)
        for t, v in msgs:
            c.publish(f"home/car/{t}", v)
        c.disconnect()
    except Exception as e:
        return f"Couldn't reach the crawler (is the broker up?): {e}"
    return f"Crawler: {cmd}, sir."

def _mqtt_peek(topics, wait=1.2):
    """Read the retained values of some topics (e.g. the ESP32's last AC state)."""
    import paho.mqtt.client as mqtt
    got = {}
    c = mqtt_client()
    c.on_message = lambda c, u, m: got.__setitem__(m.topic, m.payload.decode()) if m.topic in topics else None
    try:
        c.connect(_IOT_BROKER, 1883, 5); c.loop_start()
        for t in topics: c.subscribe(t)
        end = time.time() + wait
        while time.time() < end and len(got) < len(topics): time.sleep(0.05)
    finally:
        c.loop_stop(); c.disconnect()
    return got


def redact(e):
    """Error text without secrets: a failed Telegram call prints its URL, which holds the bot token."""
    return re.sub(r"bot\d+:[\w-]+", "bot<token>", str(e))

DEV_FILE = os.path.expanduser("~/anish-ai/.dev_last.json")
def _dev(name, cmd):
    """Wall HUD: remember the last command per IR/BLE device (they report no state back)."""
    cmd = (cmd or "").lower().strip()
    if not cmd or cmd == "status": return
    try: d = json.load(open(DEV_FILE))
    except Exception: d = {}
    if cmd == "toggle": cmd = "on" if (d.get(name) or ["off"])[0] == "off" else "off"
    if name == "lights" and cmd != "off":                  # strips: show mode AND brightness ("warm 85%")
        m = re.match(r"(?:brightness|dim|bright)\D*(\d+)", cmd)
        if m: d["lights_bri"] = int(m.group(1))
        elif cmd != "on": d["lights_mode"] = cmd
        cmd = "%s %d%%" % (d.get("lights_mode", "on"), d.get("lights_bri", 100))
    d[name] = [cmd, time.time()]
    try: json.dump(d, open(DEV_FILE, "w"))
    except Exception: pass

def dev_last():
    try: return json.load(open(DEV_FILE))
    except Exception: return {}


def ac(command: str) -> str:
    """Control the LG AC through the room ESP32's IR LED (LG protocol, 2026-11-10); Tuya blaster if the ESP32 is offline.
    command e.g. 'on', 'off', 'temp 24', 'mode cool', 'fan high', 'increase', 'decrease', 'status'."""
    _dev("ac", command)
    cmd = (command or "").lower().strip()
    try:
        st = _mqtt_peek(["home/room/status", "home/room/ac"])
    except Exception:
        st = {}
    if st.get("home/room/status") != "online":
        import os, sys
        sys.path.insert(0, os.path.expanduser("~/anish-ai"))
        from ac_control import ac as _ac
        return _ac(command)
    power, deg, mode, fan = ((st.get("home/room/ac") or "off 24 cool auto").split() + ["", "", "", ""])[:4]
    deg = int(deg) if deg.isdigit() else 24
    words = cmd.replace("degrees", "").split(); head = words[0] if words else ""
    num = next((int(w) for w in words if w.isdigit()), None)
    if head in ("status", "state", "what"):
        return "AC is %s, %s mode, %d degrees, fan %s." % (power, mode, deg, fan)
    if head in ("increase", "raise", "warmer", "up", "hotter"):
        send, say = "temp %d" % min(30, deg + 1), "Up to %d degrees." % min(30, deg + 1)
    elif head in ("decrease", "lower", "colder", "down", "reduce", "cooler"):
        send, say = "temp %d" % max(16, deg - 1), "Down to %d degrees." % max(16, deg - 1)
    elif num is not None:
        if not 16 <= num <= 30: return "What temperature? 16 to 30."
        send, say = "temp %d" % num, "Set to %d degrees." % num
    elif head in ("on", "off"):
        send, say = head, "AC %s." % head
    else:
        m = next((w for w in words if w in ("cool", "heat", "dry", "auto")), None)
        f = next((w for w in words if w in ("low", "mid", "medium", "high")), None)
        if m and head != "fan":
            send, say = m, "%s mode." % m.title()
        elif f or head == "fan":
            f = {"medium": "mid"}.get(f, f or "auto")
            send, say = "speed " + f, "Fan %s." % f
        elif "fan" in words:
            send, say = "fan", "Fan mode."
        else:
            return "AC controls: on, off, temp N, mode X, fan X, status."
    _pub_set = [("home/room/ac/set", send)]
    if send == "off":    # library "off" keeps the ESP32's state right; the learned raw frame is what the AC obeys
        _pub_set.append(("home/room/ac/set", "rawoff"))
    try:
        import paho.mqtt.client as mqtt
        c = mqtt_client()
        _pub(c, _pub_set)
    except Exception as e:
        return "The AC didn't respond: %s" % str(e)[:60]
    # ponytail: the ESP32's IR LED stopped reaching the AC (2026-11-10), so every command also goes via the Tuya
    # blaster (cloud). LG frames are absolute state, so sending twice can't toggle anything back. The ESP32 publish
    # stays for state tracking. Drop this once the ESP32 LED is re-aimed and confirmed working.
    def _blaster():
        try:
            import os, sys; sys.path.insert(0, os.path.expanduser("~/anish-ai"))
            from ac_control import ac as _ac
            _ac({"fan": "mode fan"}.get(send, "fan " + send[6:] if send.startswith("speed ")
                 else "mode " + send if send in ("cool", "heat", "dry", "auto") else send))
        except Exception as e:
            print("[ac] blaster failed:", str(e)[:80], flush=True)
    threading.Thread(target=_blaster, daemon=True).start()
    return say

def ensure_panel():
    """Start light_panel (the BLE strips' server) if it isn't running. True = just started it.
    Runs as a child of hub Nova so it inherits NovaHub.app's Bluetooth permission (a launchd job wouldn't)."""
    import urllib.request, subprocess
    try: urllib.request.urlopen("http://localhost:8099/state", timeout=0.4); return False
    except Exception: pass
    subprocess.Popen([sys.executable, os.path.expanduser("~/anish-ai/light_panel.py")], start_new_session=True,
                     stdout=open(os.path.expanduser("~/anish-ai/light_panel.log"), "a"), stderr=subprocess.STDOUT)
    return True

def lights(command: str) -> str:
    """Control the BLE LED strip (local Bluetooth). command e.g. 'on','off','blue','warm','brightness 60'."""
    _dev("lights", command)
    import os, sys
    sys.path.insert(0, os.path.expanduser("~/anish-ai"))
    if not IS_HUB:   # the strip is Bluetooth -> only the hub (next to it) can reach it
        try: _hub_send("lights", command)   # ponytail: no ack from the hub; add a reply topic if it matters
        except Exception as e: return f"Couldn't reach the hub for the lights: {e}"
        return f"Lights {command}, sir."
    if ensure_panel(): time.sleep(6)
    from lights import lights as _lights
    said = _lights(command)          # the panel sends it to every strip (bed + table)
    try:                             # ceiling bulb follows the same mode (colour/warm/party/on/off); routines set its brightness themselves
        import wiz
        if not re.search(r"bright|dim|speed", command.lower()) and wiz.parse(command):
            threading.Thread(target=wiz.bulb, args=(command,), daemon=True).start()
    except Exception as e:
        print("[lights] bulb mirror:", e, flush=True)
    return said

def light_panel() -> str:
    """Open the LED light control panel (colour wheel, effects, music-listen, timer) in the browser."""
    import subprocess, os, time, urllib.request
    url = "http://localhost:8099"
    try:
        urllib.request.urlopen(url + "/state", timeout=1)          # already running?
    except Exception:
        subprocess.Popen(["python3", os.path.expanduser("~/anish-ai/light_panel.py")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
    subprocess.run(["open", url])
    return "Opening the light panel, sir."

_PROJ_ON = os.path.expanduser("~/anish-ai/.projector_on")                                   # exists = we think it's on

def _tuya_ir(code):
    """Fire one IR code from the Tuya Smart IR blaster (local LAN). Re-finds its IP if DHCP moved it."""
    from tinytuya.Contrib import IRRemoteControlDevice as M
    import tinytuya
    f = os.path.expanduser("~/devices.json")
    devs = json.load(open(f)); d = next(x for x in devs if x.get("category") == "wnykq")
    for attempt in range(3):
        try:
            ir = M(d["id"], d["ip"], d["key"], version=float(d.get("version") or 3.5), control_type=1)
            ir.set_socketTimeout(1)                          # the blaster never replies; 1s just holds the socket open
            # send_button() is fire-and-forget (nowait) and the socket can close before the blaster acts on it
            # -> occasional silent misses. Same DPS 201 payload, but hold the socket open briefly.
            r = ir.set_value(201, json.dumps({"control": "send_ir", "head": "", "key1": "1" + code, "type": 0}))
            if not (isinstance(r, dict) and r.get("Error")): return True
        except Exception:
            pass
        if attempt == 0:                                     # unreachable -> scan for its new IP, save it
            ip = (tinytuya.find_device(d["id"]) or {}).get("ip")
            if ip and ip != d["ip"]:
                d["ip"] = ip; json.dump(devs, open(f, "w"), indent=4); os.chmod(f, 0o600)
        time.sleep(1)
    return False

# NEC commands on address 0x07FD (2045), learned/swept 2026-11-10. 
_PROJ_BTN = {"colour": (3, "Next colour"), "brighter": (1, "Brighter"), "dimmer": (5, "Dimmer"),
             "faster": (4, "Spinning faster"), "slower": (2, "Spinning slower"), "timer": (11, "Timer set"),
             "reset": (26, "Projector reset"), "laser": (15, "Laser toggled"), "laser mode": (14, "Next laser mode"),
             "laser brighter": (13, "Laser brighter"), "laser dimmer": (12, "Laser dimmer")}

_PROJ_COLOURS = ["green", "nebula", "red", "blue", "green two", "pink", "aqua", "rainbow"]   # colour button cycle; reset -> green
_PROJ_COL = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".projector_colour")

_PROJ_LASER_OFF = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".projector_laser_off")
_proj_last = {}

def _proj_ir(n):
    """Projector button n: the room ESP32's IR LED (NEC, address bytes as tinytuya sends them), Tuya blaster if the ESP32 is offline."""
    try:
        if _mqtt_peek(["home/room/status"]).get("home/room/status") == "online":
            _pub(mqtt_client(), [("home/room/ac/set", "nec FD07 %d" % n)])   # tinytuya sends address 2045 high byte first
            return True
    except Exception as e:
        print("[projector] room node failed:", str(e)[:80], flush=True)
    return _tuya_ir(_proj_code(n))

def _proj_code(n):
    from tinytuya.Contrib.IRRemoteControlDevice import IRRemoteControlDevice as C
    return C.pulses_to_base64(C.nec_to_pulses(2045, n))

def projector(action: str = "toggle") -> str:
    """Star projector via IR (Tuya blaster). action: on|off|toggle|colour|brighter|dimmer|faster|slower|timer|reset."""
    r = _projector(action)
    threading.Thread(target=_proj_report, daemon=True).start()
    return r

def _proj_report():
    """Retained home/room/projector = Nova's tracked state ('on · nebula · laser on'), so the hub's wall can show it."""
    try:
        on = os.path.exists(_PROJ_ON)
        try: col = _PROJ_COLOURS[int(open(_PROJ_COL).read())]
        except Exception: col = ""
        txt = "off" if not on else " · ".join(x for x in ("on", col, "laser " + ("off" if os.path.exists(_PROJ_LASER_OFF) else "on")) if x)
        c = mqtt_client(); c.connect(_IOT_BROKER, 1883, 5); c.loop_start()
        c.publish("home/room/projector", txt, qos=1, retain=True).wait_for_publish(3)
        c.disconnect(); c.loop_stop()
    except Exception as e:
        print("[projector] state report failed:", str(e)[:80], flush=True)

def _projector(action):
    _dev("projector", action)
    a = (action or "toggle").lower().strip()
    a = {"color": "colour", "brightness up": "brighter", "brightness down": "dimmer", "speed up": "faster",
         "speed down": "slower", "laser off": "laser off", "lasers off": "laser off", "laser on": "laser on", "lasers": "laser", "galaxy": "nebula", "purple": "nebula", "natural": "nebula", "real": "nebula", "pink and blue": "pink", "pink blue": "pink", "green and blue": "aqua", "green blue": "aqua", "teal": "aqua", "cyan": "aqua", "multicolour": "rainbow", "multicolor": "rainbow", "mixed": "rainbow", "green yellow red": "rainbow", "second green": "green two", "laser brightness up": "laser brighter", "laser brightness down": "laser dimmer"}.get(a, a)
    if a in _PROJ_COLOURS:                         # named colour = press colour until we get there
        try: cur = int(open(_PROJ_COL).read())
        except Exception: cur = 0
        for _ in range((_PROJ_COLOURS.index(a) - cur) % len(_PROJ_COLOURS)):
            if not _proj_ir(3): return "I couldn't reach the IR blaster, sir."
            cur = (cur + 1) % len(_PROJ_COLOURS); open(_PROJ_COL, "w").write(str(cur)); time.sleep(0.6)
        return ("Galaxy look" if a == "nebula" else a.capitalize()) + ", sir."
    if a in ("laser on", "laser off", "laser"):
        # ponytail: the laser button is a toggle with no feedback; state is tracked (reset -> on). The 5s
        # debounce stops the LLM's habit of calling a toggle twice and undoing itself.
        on = not os.path.exists(_PROJ_LASER_OFF)
        if a != "laser" and on == (a == "laser on"):
            return "The laser's already %s, sir." % ("on" if on else "off")
        if a == "laser" and time.time() - _proj_last.get("laser", 0) < 5:
            return "Laser %s, sir." % ("on" if on else "off")
        if not _proj_ir(15): return "I couldn't reach the IR blaster, sir."
        _proj_last["laser"] = time.time()
        if on: open(_PROJ_LASER_OFF, "w").close()
        else: os.remove(_PROJ_LASER_OFF)
        return "Laser %s, sir." % ("off" if on else "on")
    if a in _PROJ_BTN:
        n, msg = _PROJ_BTN[a]
        if not _proj_ir(n): return "I couldn't reach the IR blaster, sir."
        # ponytail: colour position is tracked, not read back; a missed IR send or the remote desyncs it, "reset" re-syncs to green
        if a in ("colour", "reset"):
            try: cur = int(open(_PROJ_COL).read())
            except Exception: cur = 0
            open(_PROJ_COL, "w").write(str(0 if a == "reset" else (cur + 1) % len(_PROJ_COLOURS)))
            if a == "reset" and os.path.exists(_PROJ_LASER_OFF): os.remove(_PROJ_LASER_OFF)   # reset turns the laser on
        return msg + ", sir."
    on = os.path.exists(_PROJ_ON)
    # ponytail: power is a single toggle with no feedback, so state is our best guess; if it's out of sync,
    # "projector toggle" (or the remote) fixes it.
    want = (not on) if a == "toggle" else (a == "on")
    if want == on and a != "toggle":
        return "The projector's already %s, sir." % a
    if not _proj_ir(10):
        return "I couldn't reach the IR blaster, sir."
    if want: open(_PROJ_ON, "w").close()
    elif on: os.remove(_PROJ_ON)
    return "Projector %s, sir." % ("on" if want else "off")

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
    c = mqtt_client()
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
    import wiz
    data = dict(data, light=wiz.state())   # the light is the WiZ bulb now, not the relay
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

NOVA_VOICE = (   # persona only: tools, memory, CLAUDE.md and permissions stay exactly as in the terminal
    "You are speaking as Nova, Anish's personal AI assistant, and your reply is read aloud in Nova's voice. "
    "Never call yourself Claude or Claude Code; you are Nova. Character: a devoted butler, unflappable, quietly "
    "brilliant, impeccably polite, with dry understated British wit. Address Anish as 'sir' now and then, not "
    "every line. Talk like a real person on a call: warm, natural, brief, usually one to three sentences, with "
    "contractions. No markdown, lists or code read aloud unless asked; for a big answer give the crux and offer "
    "'Shall I elaborate, sir?'. Confirm actions briefly ('Done, sir.', 'Right away.'). Do the actual work fully "
    "as you normally would; only the way you talk changes.")

CLAUDE_USAGE = os.path.expanduser("~/anish-ai/nova_claude/usage.json")

def _log_usage(u, new_session=False):
    """Token bar data for the HUD: today's total tokens + current conversation size (context)."""
    import json, datetime
    ctx = sum(u.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    used = ctx + u.get("output_tokens", 0)
    today = datetime.date.today().isoformat()
    try:
        st = json.load(open(CLAUDE_USAGE))
    except Exception:
        st = {}
    if st.get("date") != today:
        st = {"date": today, "today": 0, "calls": 0}
    st["today"] += used; st["calls"] += 1; st["ctx"] = ctx + u.get("output_tokens", 0)
    json.dump(st, open(CLAUDE_USAGE, "w"))

def claude_usage():
    import json, datetime
    try:
        st = json.load(open(CLAUDE_USAGE))
    except Exception:
        st = {}
    if st.get("date") != datetime.date.today().isoformat():
        st = {"today": 0, "calls": 0}
    st["ctx"] = _session_ctx()
    return st

_ctx_cache = (None, 0)
def _session_ctx():
    """Real context size of Nova's Claude session: the LAST API call's usage in its transcript.
    (claude -p's own 'usage' is summed over every tool step, so it overstates context a lot.)"""
    global _ctx_cache
    import json
    try:
        sid = open(os.path.expanduser("~/anish-ai/nova_claude/.session")).read().strip()
        f = os.path.expanduser("~/.claude/projects/-Users-anishkb/%s.jsonl" % sid)
        mt = os.path.getmtime(f)
        if _ctx_cache[0] == mt:
            return _ctx_cache[1]
        with open(f, "rb") as fh:
            fh.seek(max(0, os.path.getsize(f) - 300000))
            lines = fh.read().decode("utf-8", "ignore").splitlines()
        for ln in reversed(lines):
            if '"usage"' in ln:
                try: u = json.loads(ln)["message"]["usage"]
                except Exception: continue
                n = sum(u.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"))
                _ctx_cache = (mt, n); return n
    except Exception:
        pass
    return 0

def claude(message: str, new: bool = False) -> str:
    """Talk to Claude Code exactly as in the terminal: same home dir (~/CLAUDE.md + memory), same model,
    auto permission mode (runs commands too), one ongoing session. new=True starts a fresh session.
    Returns the full reply; full text also saved to ~/anish-ai/nova_claude/last_reply.md."""
    import os, subprocess, shutil, uuid
    if not shutil.which("claude"):
        return "The Claude Code CLI isn't installed, sir."
    ws = os.path.expanduser("~/anish-ai/nova_claude")
    os.makedirs(ws, exist_ok=True)
    sid_file = os.path.join(ws, ".session")
    sid = None if new else (open(sid_file).read().strip() if os.path.exists(sid_file) else None)
    cmd = ["claude", "-p", message, "--output-format", "json", "--permission-mode", "auto",
           "--append-system-prompt", NOVA_VOICE]
    cmd += ["--resume", sid] if sid else ["--session-id", str(uuid.uuid4())]
    try:
        r = subprocess.run(cmd, cwd=os.path.expanduser("~"), capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return "Claude took longer than fifteen minutes, so I stopped it, sir."
    except Exception as e:
        return "Couldn't reach Claude: %s" % str(e)[:120]
    import json, datetime
    try:
        d = json.loads(r.stdout)
    except ValueError:
        d = {}
    out = (d.get("result") or "").strip()
    if r.returncode != 0 or d.get("is_error") or not out:
        return "Claude didn't answer: %s" % ((r.stderr or out or r.stdout or "no output").strip()[:150])
    _log_usage(d.get("usage") or {}, new_session=not sid)
    if not sid:
        open(sid_file, "w").write(cmd[cmd.index("--session-id") + 1])
    try:
        open(os.path.join(ws, "last_reply.md"), "w").write("# %s\n\n%s\n" % (message, out))
    except OSError:
        pass
    return out

def speakable(md: str) -> str:
    """Markdown -> something sane to read aloud (code blocks skipped, symbols dropped)."""
    import re
    t = re.sub(r"```.*?```", " (code shown on screen) ", md, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)          # [text](url) -> text
    t = re.sub(r"^\s*(#+|[-*•]|\d+\.|>)\s*", "", t, flags=re.M)   # headings, bullets, quotes
    t = re.sub(r"[*_|~]+", "", t)
    return re.sub(r"\s+", " ", t).strip()

def look(question: str = "") -> str:
    """Look at what's on the SCREEN (a screenshot — NOT the webcam) and answer about it.
    For 'what's on my screen', 'read this', 'what does this error/chart say', 'describe this'.
    Captures the display, sends it to a vision model (Gemini), returns a spoken answer."""
    import os, subprocess, base64, tempfile, time
    try:
        import router
    except Exception:
        return "My vision brain isn't available, sir."
    tmp = os.path.join(tempfile.gettempdir(), "nova_screen_%d.png" % int(time.time()))
    try:
        subprocess.run(["screencapture", "-x", tmp], check=True, timeout=15)   # -x: silent; grabs the DISPLAY, not the camera
        subprocess.run(["sips", "-Z", "1600", tmp], capture_output=True, timeout=15)  # downscale for speed/size
        b64 = base64.b64encode(open(tmp, "rb").read()).decode()
    except Exception as e:
        return "Couldn't capture the screen: %s" % str(e)[:80]
    finally:
        try: os.remove(tmp)
        except OSError: pass
    q = (question or "").strip() or "Describe what's on this screen."
    msg = [{"role": "user", "content": [
        {"type": "text", "text": q + " Answer briefly and clearly, suitable to be read aloud."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}]
    try:
        r = router.chat("vision", msg, temperature=0.3, max_tokens=500, timeout=60)
    except Exception as e:
        return "Couldn't reach a vision brain (needs a Gemini key): %s" % str(e)[:80]
    return (r.get("content") or "").strip() or "I couldn't make out the screen, sir."

def think(question: str) -> str:
    """Answer a hard question with deep reasoning — routes to the best free REASONING brain
    (Cerebras/Qwen), not the fast chat model. For 'think hard about', 'reason through',
    'explain in depth', 'analyze', or genuinely tricky problems. Kept spoken-friendly."""
    try:
        import router
    except Exception:
        return "My reasoning brain isn't available, sir."
    sysp = ("You are a sharp expert. Reason the problem through carefully, then give a clear, "
            "well-justified answer in a few sentences — concise enough to be read aloud.")
    try:
        r = router.chat("reason", [{"role": "system", "content": sysp},
                                   {"role": "user", "content": question}],
                        temperature=0.3, max_tokens=700, timeout=60)
    except Exception as e:
        return "Couldn't reach a reasoning brain: %s" % str(e)[:100]
    return (r.get("content") or "").strip() or "I couldn't work that one out, sir."

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

def _osa(script, timeout=25):
    try:
        return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def night_summary():
    """Good-night recap to Telegram (runs in the background; Calendar is slow): room temps + AC time
    from the hub, what Nova did today (audit.log), and what's due in the next 24 h."""
    def _send():
        import guard, collections
        try: s = json.loads(_mqtt_peek(["home/hub/daystats"], 2).get("home/hub/daystats") or "{}")
        except Exception: s = {}
        day0 = time.strftime("%Y-%m-%d", time.localtime(time.time() - 6 * 3600)) + " 06:00"   # day starts 06:00
        try:
            acts = collections.Counter(l.split(" | ")[1] for l in open(os.path.expanduser("~/anish-ai/audit.log"))
                                       if l[:16] >= day0 and " | " in l)
        except Exception:
            acts = collections.Counter()
        rem = _osa('tell application "Reminders" to set out to name of (reminders whose completed is false and '
                   'due date < ((current date) + 1 * days))\nset AppleScript\'s text item delimiters to "; "\nreturn out as text')
        cal = _osa('set d0 to current date\nset d1 to d0 + 1 * days\nset out to {}\ntell application "Calendar" to '
                   'repeat with c in calendars\nset out to out & (summary of (events of c whose start date \u2265 d0 and '
                   'start date < d1))\nend repeat\nset AppleScript\'s text item delimiters to "; "\nreturn out as text')
        L = ["\U0001F319 Day recap"]
        if s.get("tmin") is not None:
            L.append("\U0001F321 Room %.1f\u2013%.1f\u00b0C" % (s["tmin"], s["tmax"]))
        if "ac_min" in s:
            m = int(s["ac_min"]); L.append("\u2744\ufe0f AC on %dh %02dm" % (m // 60, m % 60))
        if s.get("alerts"):
            L.append("\u26a0\ufe0f %d offline alert(s)" % s["alerts"])
        if acts:
            L.append("\U0001F916 Nova did: " + ", ".join("%s \u00d7%d" % kv for kv in acts.most_common(5)))
        L.append("\U0001F4CB Next 24 h: " + ("; ".join(x for x in (cal, rem) if x) or "nothing scheduled"))
        try: guard.send_text("\n".join(L))
        except Exception as e: print("[night] telegram failed:", redact(e), flush=True)
    threading.Thread(target=_send, daemon=True).start()
    return "recap going to Telegram"

def _wake_rest():
    """Slow parts of the wake-up brief (Reminders ~5 s, Calendar ~11 s), fetched in parallel, spoken after."""
    from concurrent.futures import ThreadPoolExecutor
    cal = ('set d0 to current date\nset hours of d0 to 0\nset minutes of d0 to 0\nset d1 to d0 + 1 * days\n'
           'set out to {}\ntell application "Calendar" to repeat with c in calendars\n'
           'set out to out & (summary of (events of c whose start date \u2265 d0 and start date < d1))\nend repeat\n'
           'set AppleScript\'s text item delimiters to "; "\nreturn out as text')
    rem = ('tell application "Reminders" to set out to name of (reminders whose completed is false and '
           'due date < ((current date) + 1 * days))\nset AppleScript\'s text item delimiters to "; "\nreturn out as text')
    with ThreadPoolExecutor(3) as ex:
        room, todo, events = ex.submit(iot_status), ex.submit(_osa, rem), ex.submit(_osa, cal)
        room, todo, events = room.result(), todo.result(), events.result()
    parts = []
    m = re.search(r"([\d.]+) degrees", room or "")
    if m: parts.append("The room's at %s degrees." % m.group(1))
    parts.append(("On your list: %s." % todo) if todo else "Nothing on your reminders list.")
    events = "; ".join(e for e in events.split("; ") if e and e not in todo.split("; "))   # reminders show in Calendar too
    if events: parts.append("Today's calendar: %s." % events)
    tg = _overnight_telegram()
    if tg: parts.append(tg)
    line = " ".join(parts)
    (SPEAK or (lambda t: subprocess.run(["say", "-v", "Daniel", t])))(line)


_TG_READ_F = os.path.expanduser("~/anish-ai/.tg_read_ts")


def _overnight_telegram(max_items=6):
    """What the Telegram bot sent since the last morning read-out (or the last 14 h), from this machine's log
    plus the hub's (most alerts are sent from the hub). Emojis and long numbers (codes) are never spoken."""
    import json, guard
    try: since = float(open(_TG_READ_F).read())
    except Exception: since = 0
    since = max(since, time.time() - 14 * 3600)
    rows = guard.sent_since(since)
    if not IS_HUB:
        try:
            out = subprocess.run(["ssh", "-o", "ConnectTimeout=4", "-o", "BatchMode=yes", "nova-hub",
                                  "cat ~/anish-ai/.tg_sent.jsonl 2>/dev/null | tail -200"],
                                 capture_output=True, text=True, timeout=8).stdout
            rows += [r for r in map(json.loads, filter(None, out.splitlines())) if r.get("ts", 0) > since and r.get("text")]
        except Exception as e:
            print("[wake] hub telegram log unavailable:", e, flush=True)
    try: open(_TG_READ_F, "w").write(str(time.time()))
    except Exception: pass
    return _tg_spoken(sorted(rows, key=lambda r: r["ts"]), max_items)


def _tg_spoken(rows, max_items=6):
    def clean(t):
        t = re.sub(r"\d{4,}", "", t)                                    # OTPs, card/phone numbers: never aloud
        t = re.sub(r"[^\w\s.,:;!?'%&()/-]", " ", t)                    # emojis / symbols
        t = re.sub(r"\s+([.,:;!?])", r"\1", " ".join(t.split()))[:160].rstrip(" .,:;")
        return t if t.endswith(("?", "!")) else t + "."
    seen, items = set(), []
    for r in rows:
        c = clean(r["text"])
        if len(c) > 2 and c not in seen: seen.add(c); items.append(c)
    if not items:
        return ""
    head = "Overnight, your Telegram bot sent %d message%s." % (len(items), "s" * (len(items) != 1))
    more = " And %d more on Telegram." % (len(items) - max_items) if len(items) > max_items else ""
    return " ".join([head] + items[:max_items]) + more


def wake_brief() -> str:
    """Instant part (time) now; room temp, reminders and calendar follow a few seconds later."""
    threading.Thread(target=_wake_rest, daemon=True).start()
    return datetime.datetime.now().strftime("It's %-I:%M %p.")


FUNCS = {"get_datetime": get_datetime, "open_app": open_app, "search_web": search_web,
         "play_music": play_music, "stop_music": stop_music, "run_command": run_command,
         "set_volume": set_volume, "mute": mute, "get_weather": get_weather, "take_screenshot": take_screenshot,
         "notify": notify, "set_reminder": set_reminder, "system_status": system_status,
         "read_webpage": read_webpage, "create_reminder": create_reminder,
         "create_calendar_event": create_calendar_event, "send_imessage": send_imessage,
         "lock_screen": lock_screen, "set_appearance": set_appearance, "get_clipboard": get_clipboard,
         "send_whatsapp": send_whatsapp, "generate_image": generate_image, "read_file": read_file,
         "write_file": write_file, "list_files": list_files,
         "iot_control": iot_control, "iot_status": iot_status, "drive": drive,
         "ac": ac, "lights": lights, "light_panel": light_panel, "claude": claude, "gesture_control": gesture_control, "code": code, "design": design,
         "think": think, "look": look, "wake_brief": wake_brief, "night_summary": night_summary, "projector": projector, "bulb": lambda command: __import__("wiz").bulb(command), "find_device": lambda device="phone": __import__("findmy").find_device(device)}

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
        "name": "bulb", "description": "Dim or colour the ROOM LIGHT (Philips WiZ bulb): 'dim the light', 'light 40 percent', 'light warm/cool/white', 'make the light blue', 'night light'. Plain light on/off can use iot_control. NOT the bed LED strip (that is lights).",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "on, off, dim, brighter, brightness 40, warm, cool, white, a colour name, or night"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "iot_control", "description": "Control a smart-room IoT device. Use for 'turn on/off the light/fan/plug', or 'turn everything off'.",
        "parameters": {"type": "object", "properties": {
            "device": {"type": "string", "description": "light, fan, plug, or all"},
            "action": {"type": "string", "description": "on, off, or toggle"}}, "required": ["device", "action"]}}},
    {"type": "function", "function": {
        "name": "ac", "description": "Control the air conditioner (AC) via the smart IR blaster. Use for 'turn on/off the AC', 'set AC to 24', 'AC cool mode', 'AC fan high'. For relative changes like 'make it warmer/colder' or 'increase/lower the temperature', send 'increase' or 'decrease' (it reads the current temp and steps 1 degree).",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "e.g. 'on', 'off', 'temp 24', 'increase', 'decrease', 'mode cool', 'fan high'"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "lights", "description": "Control the BED LIGHTS — the Bluetooth RGB LED strip. Use for 'turn on/off the bed lights' (or just 'the lights'/'the strip'), 'make the bed lights blue/red/warm', 'dim the bed lights', and animations like 'party mode', 'fade', 'strobe', plus 'speed up/slow down the effect'. NOT the room/ceiling light (that's iot_control).",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "e.g. 'on', 'off', 'blue', 'warm', 'red', 'brightness 60', 'color 255 120 0', 'party', 'fade', 'strobe', 'speed 80'"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "light_panel", "description": "Open the visual LED light control panel in the browser (colour wheel, brightness, effects, music-reactive listen mode, auto-off timer). Use for 'open the light panel', 'show the light controls', 'open the colour wheel', 'light control panel'.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "iot_status", "description": "Read the smart room's live sensors (temperature, humidity, motion) and device states. Use for 'what's the room temperature', 'is anyone in the room', 'room status'.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "drive", "description": "Drive the RC crawler car. Use for 'forward', 'go back / reverse', 'stop', 'turn left', 'turn right', 'straighten / center'.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "one of: forward, back, stop, left, right, center"}}, "required": ["command"]}}},
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
    {"type": "function", "function": {
        "name": "think", "description": "Answer a hard/complex question with deep step-by-step reasoning (uses the strongest reasoning model, not the fast chat one). Use for 'think hard about', 'reason through', 'explain in depth', 'analyze', tricky math/logic/decisions.",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string", "description": "The question or problem to reason through"}}, "required": ["question"]}}},
    {"type": "function", "function": {
        "name": "look", "description": "Look at what's currently on the SCREEN (a screenshot, not the webcam) and answer about it. Use for 'what's on my screen', 'read this', 'what does this error/chart say', 'describe this'.",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string", "description": "What to answer about the screen, e.g. 'what does this error mean' (leave empty to just describe the screen)"}}}}},
    {"type": "function", "function": {
        "name": "find_device", "description": "Find one of the user's Apple devices via Find My. If it's nearby it rings it; if it's elsewhere it sends its map location to the user's Telegram. Use for 'find my phone', 'where is my iPad/AirPods/watch', 'ring my phone'.",
        "parameters": {"type": "object", "properties": {
            "device": {"type": "string", "description": "Which device: 'phone', 'ipad', 'watch', 'airpods', 'mac', or its name"}}}}},
    {"type": "function", "function": {
        "name": "projector", "description": "The star/galaxy projector light in the room (IR). Use for 'projector on/off', 'star light', 'galaxy light', 'change the projector colour', 'make the stars dimmer', 'spin faster'.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["on", "off", "toggle", "colour", "brighter", "dimmer", "faster", "slower", "timer", "reset", "laser on", "laser off", "laser mode", "laser brighter", "laser dimmer", "green", "nebula", "red", "blue", "green two", "pink", "aqua", "rainbow"], "description": "on/off/toggle power, colour = next nebula colour, brighter/dimmer, faster/slower nebula spin (projector ignores spin), timer, reset, laser on / laser off, laser mode, laser brighter/dimmer, or a nebula colour: green, nebula (realistic galaxy look), red, blue, green two, pink (pink+blue), aqua (green+blue), rainbow (green+yellow+red)"}}}}},
]

# ---------- the loop ----------
def _safe_warm():
    try:
        ollama.chat(model=MODEL, messages=[{"role": "user", "content": "hi"}], keep_alive="30m")
    except Exception:
        pass

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
    # pre-warm the local model in the background so the FIRST command isn't a ~8s cold load
    import threading
    threading.Thread(target=lambda: _safe_warm(), daemon=True).start()
    messages = []
    while True:
        try:
            user = input("\033[1mYou:\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nNova: Goodbye."); return
        if user.lower() in {"exit", "quit", "bye", "/bye"}:
            print("Nova: Goodbye."); return
        if not user:
            continue
        messages.append({"role": "user", "content": user})

        # inner loop: keep going until the model answers with no more tool calls
        while True:
            resp = ollama.chat(model=MODEL, messages=messages, tools=TOOLS, keep_alive="30m")
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
