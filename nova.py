#!/usr/bin/env python3
"""Nova v1 — text assistant on the local Qwen (anish-ai) with tool-calling 'hands'.
Run:  python3 ~/anish-ai/nova.py      (needs Ollama running; it usually is)
Quit: type 'exit' or Ctrl-C."""
import urllib.parse, subprocess, sys, json, datetime, os, glob, time, threading, re, shutil, ollama
if not shutil.which("claude"):     # Claude Code comes from nvm, which NovaMac.app's launchd PATH doesn't include
    _cc = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/claude")), key=lambda p: [int(x) for x in re.findall(r"\d+", p.split("/node/")[1].split("/")[0])])
    if _cc: os.environ["PATH"] = os.path.dirname(_cc[-1]) + os.pathsep + os.environ.get("PATH", "")

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

_player = None            # the running afplay (music) process, if any
_TRACK = "/tmp/nova_track"
NOW_F = "/tmp/nova_now.txt"   # title of the song playing (the hub page shows it)

def _ytdlp() -> str:
    # prefer the pip 'nightly' build (keeps up with YouTube); fall back to brew, then PATH
    for p in (os.path.expanduser("~/Library/Python/3.14/bin/yt-dlp"), "/opt/homebrew/bin/yt-dlp",
              os.path.join(os.path.dirname(sys.executable), "yt-dlp")):   # last = venv (Intel hub, no brew)
        if os.path.exists(p):
            return p
    return "yt-dlp"

MUSIC_VOL = 0.4      # calibration knob: music level relative to the speaker's volume (user: "always 40%")
MUSIC_FADE_S = 3.0   # fade-in length

def _fade_in(src, secs=MUSIC_FADE_S):
    """Decode to WAV with macOS's built-in afconvert and ramp the first `secs` up from silence (afplay can't fade)."""
    import wave, array
    wav = _TRACK + ".wav"
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16", src, wav], check=True, capture_output=True, timeout=60)
    with wave.open(wav) as w:
        p = w.getparams(); data = bytearray(w.readframes(p.nframes))
    n = min(p.nframes, int(secs * p.framerate)) * p.nchannels      # interleaved samples in the ramp
    a = array.array("h", bytes(data[:n * 2]))
    for i in range(n):
        a[i] = int(a[i] * (i / n) ** 2)                              # squared ramp: sounds even to the ear
    data[:n * 2] = a.tobytes()
    with wave.open(wav, "wb") as w:
        w.setparams(p); w.writeframes(bytes(data))
    return wav

MUSIC_AUTOPLAY = True   # when the queue runs out, keep going with YouTube Music's radio for the last song
MY_PLAYLIST = "https://music.youtube.com/playlist?list=PLHhDPWA2A4bU"   # "Spotify Liked Songs" (unlisted) for "play my playlist"
_queue = []             # [(url, title)] still to play
_played = set()         # video ids played this session (radio skips them)
_gen = 0                # bumped by every play/stop: a finished song only advances if nothing replaced it
_mlock = threading.RLock()

def _fetch(src):
    """Download one track from src (a search/watch URL) to _TRACK.*; returns (title, id) or an error string."""
    for f in glob.glob(_TRACK + ".*"):
        try: os.remove(f)
        except OSError: pass
    try:
        r = subprocess.run([_ytdlp(), "-f", "bestaudio[ext=m4a]/bestaudio", "--playlist-items", "1", "--no-update",
                            "-o", _TRACK + ".%(ext)s", "--force-overwrites",
                            "--print", "%(id)s\t%(title)s", "--no-simulate", src],
                           capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return "Timed out fetching the track — check your internet connection."
    files = glob.glob(_TRACK + ".*")
    if not files:
        err = (r.stderr or "").strip().splitlines()
        return err[-1][:200] if err else "No result."
    vid, _, title = ((r.stdout or "").strip().splitlines() or ["\t"])[0].partition("\t")
    return title or "that", vid, files[0]

def _panel_listen(on):
    """Bed + table strips follow the music (light panel's listen mode) while it plays; back to normal after. Hub only."""
    if not IS_HUB: return
    import urllib.request
    try: urllib.request.urlopen("http://localhost:8099/listen?on=%d" % on, timeout=3)
    except Exception: swallowed()                             # panel not running -> lights just stay as they are

def _start(title, vid, path):
    """Play a fetched file (fade-in, MUSIC_VOL); when it ends on its own, the next song follows."""
    global _player
    try: track = _fade_in(path)
    except Exception: swallowed(); track = path              # no fade beats no music
    # afplay on both machines (the hub has no Homebrew/mpv); below full so the mics still hear "Nova" over it
    _player = p = subprocess.Popen(["afplay", "-v", str(MUSIC_VOL), track],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if vid: _played.add(vid)
    try: open(NOW_F, "w").write(title)
    except OSError: pass
    _panel_listen(1)
    g = _gen
    def after():
        if p.wait() == 0 and g == _gen:      # 0 = played to the end (stop/skip kill it -> negative)
            r = _next(g); print("[music] next:", r, flush=True)
            if not r.startswith(("Now playing", "replaced")): _panel_listen(0)   # queue ran out
    threading.Thread(target=after, daemon=True).start()
    return "Now playing: " + title

_FLAT_F = "/tmp/nova_flat_%s.json"
FLAT_TTL = 12 * 3600   # calibration knob: re-list the playlist after this long (new songs show up then)

def _flat(url, items="1-200"):
    """[(watch url, title)] of a playlist/radio without downloading anything. Cached on disk for FLAT_TTL:
    listing the owner's 430 songs takes 10-20 s, which made every song picked on the deck/popup slow."""
    import hashlib
    f = _FLAT_F % hashlib.md5((url + items).encode()).hexdigest()[:10]
    try:
        if time.time() - os.path.getmtime(f) < FLAT_TTL: return [tuple(x) for x in json.load(open(f))]
    except (OSError, ValueError): pass
    out = _flat_fetch(url, items)
    if out:
        try: json.dump(out, open(f, "w"))
        except OSError: pass
    return out

def _flat_fetch(url, items):
    r = subprocess.run([_ytdlp(), "--no-update", "--flat-playlist", "--playlist-items", items,
                        "--print", "%(id)s\t%(title)s", url], capture_output=True, text=True, timeout=60)
    out = []
    for line in r.stdout.splitlines():
        vid, _, title = line.partition("\t")
        if vid: out.append(("https://music.youtube.com/watch?v=" + vid, title))
    return out

def _next(g=None):
    """Play the next queued song; queue empty -> radio of the last song (MUSIC_AUTOPLAY). Skips unplayable songs."""
    with _mlock:
        g = _gen if g is None else g
        for _ in range(5):                   # a few removed/blocked songs in a row, then give up
            if not _queue and MUSIC_AUTOPLAY and _played:
                last = _last_vid[0]
                _queue.extend(x for x in _flat("https://music.youtube.com/watch?v=%s&list=RDAMVM%s" % (last, last), "2-15")
                              if x[0].rsplit("=", 1)[1] not in _played)
            if not _queue: return "Queue finished."
            url, title = _queue.pop(0)
            if g != _gen: return "replaced"   # stopped / replaced while we worked
            got = _fetch(url)
            if g != _gen: return "replaced"
            if isinstance(got, tuple):
                _last_vid[0] = got[1] or _last_vid[0]
                return _start(got[0] or title, *got[1:])
        return "Couldn't play the next songs."

_last_vid = [""]   # radio seed: the song that played most recently

# Music always plays on the hub speaker (user, 2026-11-17): the Mac's brain hands every music call to the hub,
# which runs the same function locally (nova_app hub key "music") and speaks any failure itself.
_MUSIC_REMOTE = lambda: not IS_HUB
_remote_on = [False]

def _music_remote(fn, **kw):
    _hub_send("music", json.dumps({"fn": fn, "kw": kw}))
    _remote_on[0] = fn != "stop_music"
    return {"play_music": "Playing %s on the hub speaker." % kw.get("query", ""),
            "play_playlist": "Playing %s on the hub speaker." % ("that playlist" if kw.get("url") else "your playlist"),
            "next_song": "Skipping to the next song.", "stop_music": "Music stopped.", "pause_music": "Pausing or resuming the music."}[fn]

def play_music(query: str) -> str:
    """Play a song by name (YouTube Music, free, no account); more like it follows automatically. Replaces anything playing."""
    if _MUSIC_REMOTE(): return _music_remote("play_music", query=query)
    with _mlock:
        stop_music(); g = _gen
        # YouTube Music's "songs" tab first (official audio, not live/cover videos), plain YouTube if that finds nothing
        ytm = "https://music.youtube.com/search?q=" + urllib.parse.quote_plus(query) + "#songs"
        for src in (ytm, f"ytsearch1:{query}"):
            got = _fetch(src)
            if isinstance(got, tuple): break
        if not isinstance(got, tuple):
            return f"Couldn't fetch '{query}'. {got}"
        if g != _gen: return "Cancelled."         # "stop" came while it downloaded
        _last_vid[0] = got[1]
        return _start(*got)

def play_playlist(url: str = "", shuffle: bool = False, start: int = 0) -> str:
    """Play a YouTube / YouTube Music playlist song by song. No url = the user's own playlist (MY_PLAYLIST)."""
    if _MUSIC_REMOTE(): return _music_remote("play_playlist", url=url, shuffle=shuffle, start=start)
    url = (url or MY_PLAYLIST).strip()
    if not url:
        return "I don't have your playlist link yet — send it to me (public or unlisted)."
    with _mlock:
        stop_music()
        items = _flat(url, "1-2000")          # whole playlist (the user's has 430)
        if not items:
            return "I couldn't open that playlist — it may be private or the link is incomplete."
        items = items[max(0, int(start)):] or items  # start = a song picked on the hub page; the rest follow in order
        if shuffle:
            import random; random.shuffle(items)
        _queue.extend(items)
        r = _next()
        return "%s (%d songs in the playlist)" % (r, len(items)) if r.startswith("Now") else r

def next_song() -> str:
    """Skip to the next song (the playlist's next, or a similar song)."""
    if _MUSIC_REMOTE(): return _music_remote("next_song")
    global _gen
    with _mlock:
        _gen += 1                            # the killed song must not advance a second time
        subprocess.run(["pkill", "-CONT", "-f", "nova_track[.]"])   # a paused (frozen) player can't die until woken
        if _player and _player.poll() is None: _player.terminate()
        return _next()

def music_paused() -> bool:
    r = subprocess.run(["pgrep", "-f", "nova_track[.]"], capture_output=True, text=True)
    pids = r.stdout.split()
    return bool(pids) and subprocess.run(["ps", "-o", "stat=", "-p", pids[0]], capture_output=True, text=True).stdout.startswith("T")

def pause_music() -> str:
    """Pause or resume the music (toggle). Freezes the player, so it resumes mid-song."""
    if _MUSIC_REMOTE(): return _music_remote("pause_music")
    if subprocess.run(["pgrep", "-f", "nova_track[.]"], capture_output=True).returncode != 0: return "Nothing is playing."
    if music_paused():
        subprocess.run(["pkill", "-CONT", "-f", "nova_track[.]"]); return "Resumed."
    subprocess.run(["pkill", "-STOP", "-f", "nova_track[.]"]); return "Paused."

def pick_song() -> str:
    """Open the song picker popup on the Mac (the user asked for music without naming a song)."""
    url = "http://nova-hub.local:8099/pick"
    if IS_HUB:   # ponytail: fire-and-forget; if the Mac is off nobody sees it (then say a song name or 'shuffle')
        _pub(mqtt_client(), [("home/mac/pick", url)]); return "Pick a song on the Mac, sir."
    subprocess.Popen(["open", "-na", "Brave Browser", "--args", "--app=" + url, "--window-size=500,620"])
    return "Pick a song, sir."

def music_playing() -> bool:
    if _MUSIC_REMOTE(): return _remote_on[0]   # our last word to the hub (a queue that ran out isn't seen; harmless)
    return bool(_player and _player.poll() is None) or \
        subprocess.run(["pgrep", "-f", "nova_track[.]"], capture_output=True).returncode == 0   # afplay of a track

def stop_music() -> str:
    """Stop the music (and the queue / autoplay)."""
    if _MUSIC_REMOTE(): return _music_remote("stop_music")
    global _player, _gen
    _panel_listen(0)
    subprocess.run(["pkill", "-CONT", "-f", "nova_track[.]"])   # a paused (frozen) player can't die until woken
    _gen += 1; _queue.clear()               # no lock: must not wait behind a download; a pending fetch sees _gen and quits
    if _player and _player.poll() is None:
        _player.terminate()
        _player = None
        return "Music stopped."
    # backstop for a player left by a restart: match the track file, so Nova's own speech (also afplay) survives
    if subprocess.run(["pkill", "-f", "nova_track[.]"], capture_output=True).returncode == 0: return "Music stopped."
    return "Nothing was playing."

VOL_STEP = 10   # calibration knob: how much "volume up/down" changes it

def set_volume(level) -> str:
    """Set the Mac's output volume: 0-100, or "up"/"down" (+-VOL_STEP), or "+20"/"-20"."""
    try:
        s = str(level).strip().lower()
        if s in ("up", "louder", "down", "quieter", "softer") or s[:1] in "+-":
            d = VOL_STEP if s in ("up", "louder") else -VOL_STEP if s in ("down", "quieter", "softer") else int(s)
            cur = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"], capture_output=True, text=True).stdout
            s = int(cur.strip() or 50) + d
        lvl = max(0, min(100, int(s)))
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
CAM_OFF_F = os.path.expanduser("~/anish-ai/.camera_off")   # exists = owner switched the camera off (survives restarts)
MIC_MUTE_F = os.path.expanduser("~/anish-ai/.mic_mute")    # netmic ignores these sender IPs; "*" = every mic

HANDSFREE = None    # app's set_handsfree(on): the hub's own mic (set by nova_app)

def mics_off() -> bool:
    try: return "*" in open(MIC_MUTE_F).read().split()
    except OSError: return False

def camera_mic(device: str = "both", action: str = "off") -> str:
    """Owner's privacy switch. device: camera | mic | both; action: on | off. Off sticks until switched back on
    (restarts, routines and arriving home don't override it). Mic off = Nova can't hear 'mic on': use Telegram."""
    d, a = (device or "both").lower(), (action or "off").lower().strip()
    if a not in ("on", "off"): return "Say on or off."
    cam, mic = d in ("camera", "cam", "both"), d in ("mic", "mics", "microphone", "both")
    if not (cam or mic): return "Camera, mic or both?"
    if not IS_HUB:                                    # camera + mics live on the hub
        _hub_send("privacy", "%s %s" % ("both" if cam and mic else "camera" if cam else "mic", a))
        return "Camera and mic %s, sir." % a if cam and mic else "%s %s, sir." % ("Camera" if cam else "Mic", a)
    if cam:
        if a == "off":
            open(CAM_OFF_F, "w").close(); gesture_control("stop")
        else:
            if os.path.exists(CAM_OFF_F): os.remove(CAM_OFF_F)
            gesture_control("start")
    if mic:
        try: ips = set(open(MIC_MUTE_F).read().split())
        except OSError: ips = set()
        ips = ips | {"*"} if a == "off" else ips - {"*"}   # keeps any single noisy mic muted
        if ips: open(MIC_MUTE_F, "w").write("\n".join(sorted(ips)) + "\n")
        elif os.path.exists(MIC_MUTE_F): os.remove(MIC_MUTE_F)
        if HANDSFREE: HANDSFREE(a == "on")                      # the hub's own USB mic, not just the room-node mics
    what = "Camera and mics" if cam and mic else "Camera" if cam else "Mics"
    return "%s off. Turn them back on from Telegram (Cam+mic on)." % what if a == "off" and mic else "%s %s, sir." % (what, a)

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
    if (action or "start").lower().strip() != "stop" and os.path.exists(CAM_OFF_F):
        return "Camera is switched off (privacy); say 'camera on' to allow it."   # every auto-start lands here
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
        return urllib.request.urlopen(u, timeout=5).read().decode().strip()
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


_IGNORED = {}
def swallowed():
    """Log an exception we deliberately ignore - once per place+message per hour, so a loop can't flood the log.
    Replaces silent `except Exception: pass` (cleanup fix 9, 2026-11-17)."""
    e, f = sys.exc_info()[1], sys._getframe(1)
    k = "%s:%s:%d %s" % (os.path.basename(f.f_code.co_filename), f.f_code.co_name, f.f_lineno, repr(e)[:150])
    if time.time() - _IGNORED.get(k, 0) > 3600:
        _IGNORED[k] = time.time(); print("[ignored]", k, flush=True)

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
        swallowed()
    return "Pardon me, sir. A reminder: %s." % msg.rstrip(". ")

ALARM_VOL = 100     # calibration knob: hub volume for wake-up alarms, max (goodnight leaves it at 20)
ALARM_WAV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alarm.wav")

ALARM_F = os.path.expanduser("~/anish-ai/.alarm_on")     # exists while an alarm is ringing; "good morning" deletes it
ALARM_ACK_F = os.path.expanduser("~/anish-ai/.alarm_ack") # mtime = when you last said good morning
ASLEEP_F = os.path.expanduser("~/anish-ai/.asleep")         # good night's night mode (nova_automations._ASLEEP_F)
SNOOZE = 20            # calibration knob: seconds of quiet between rings (time to answer)
ALARM_MAX = 30 * 60    # failsafe: stop ringing after 30 min (you're out, or the mic is off)
AWAKE_FOR = 20 * 3600  # after "good morning", every alarm until 4 AM next day just speaks, no ring (owner 2026-11-21)
SAY_WAIT = None        # app's speak-and-wait-till-done (set by nova_app on the hub)
AWAKE_RE = re.compile(r"\b(good ?morning|i'?m (awake|up)|stop (the )?alarm)\b", re.I)

def _osa(s): return subprocess.run(["osascript", "-e", s], capture_output=True, text=True).stdout.strip()

def alarm_off(source=""):
    """'Good morning' (hub mic or Telegram): stop the ringing. True if an alarm was on."""
    open(ALARM_ACK_F, "w").write(source)
    if not os.path.exists(ALARM_F): return False
    os.remove(ALARM_F); print("[alarm] off (%s)" % source, flush=True); return True

def wake(text, say=None):
    """Hub: ring the alarm, read `text`, ring again every SNOOZE s until you say good morning (mic or Telegram),
    then read `text` once more. Volume up to ALARM_VOL for the whole thing, back afterwards."""
    say = say or SAY_WAIT or SPEAK
    try:
        ack = os.path.getmtime(ALARM_ACK_F); day = datetime.datetime.now() - datetime.timedelta(hours=4)   # a "day" starts at 4 AM
        awake = time.time() - ack < AWAKE_FOR and datetime.datetime.fromtimestamp(ack) >= day.replace(hour=4, minute=0, second=0, microsecond=0)
    except OSError: awake = False
    if awake or os.path.exists(ALARM_F):          # already up, or an alarm is already ringing -> just say it
        return say(text)
    open(ALARM_F, "w").write(text)
    try: before = int(_osa("output volume of (get volume settings)") or 0)
    except ValueError: before = None
    if before is not None and before < ALARM_VOL: _osa("set volume output volume %d" % ALARM_VOL)
    t0, first, answered = time.time(), True, False
    try:
        while os.path.exists(ALARM_F) and time.time() - t0 < ALARM_MAX:
            print("[alarm] ringing", flush=True)
            p = subprocess.Popen(["afplay", ALARM_WAV], stderr=subprocess.DEVNULL)
            while p.poll() is None and os.path.exists(ALARM_F): time.sleep(0.2)
            if p.poll() is None: p.terminate()
            if not os.path.exists(ALARM_F): break
            if first: say(text); first = False
            for _ in range(SNOOZE):
                if not os.path.exists(ALARM_F): break
                time.sleep(1)
        else:
            if os.path.exists(ALARM_F): print("[alarm] gave up after %d min" % (ALARM_MAX // 60), flush=True)
        answered = not os.path.exists(ALARM_F)
        if answered: say("Good morning, sir. " + text)   # you answered: now you're awake, hear it properly
    finally:
        if os.path.exists(ALARM_F): os.remove(ALARM_F)
        if before is not None and before < ALARM_VOL: _osa("set volume output volume %d" % before)
    if answered and os.path.exists(ASLEEP_F):    # room still in night mode -> run Morning (no more pressing it by hand)
        _hub_send("routine", "morning")

def _speak_reminder(msg):
    if IS_HUB and msg.startswith("Good morning, sir. "):   # exam-day 7:30 wake-up: ring until you say good morning
        return wake(msg[len("Good morning, sir. "):])      # exact words (no LLM rewording); wake() adds the greeting
    text = _remind_line(msg)
    if SPEAK:
        try: SPEAK(text); return
        except Exception: swallowed()
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

def _schedule(due, msg, banner=True, stale=0):
    """Fire at epoch `due` (late ones fire right away, unless more than `stale` s late), then drop it from the file."""
    def _fire():
        time.sleep(max(0, due - time.time()))
        if stale and time.time() - due > stale:              # e.g. hub was down at 7:30 -> don't say it at 10
            print("[reminder] dropped, %d min late: %s" % ((time.time() - due) // 60, msg), flush=True)
        elif banner:
            subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "Reminder"'], capture_output=True)
        if not (stale and time.time() - due > stale): _speak_reminder(msg)
        _rem_edit(lambda r: [x for x in r if (x["due"], x["msg"]) != (due, msg)])
    threading.Thread(target=_fire, daemon=True).start()

def _add_reminder(secs, msg, banner=True, stale=0):
    due = round(time.time() + secs, 1)
    _rem_edit(lambda r: r + [{"due": due, "msg": msg, "banner": banner, "stale": stale}])
    _schedule(due, msg, banner, stale)

def resume_reminders():
    """Called once at startup: re-arm reminders saved before a restart."""
    pending = _rem_edit(lambda r: r)
    for x in pending:
        _schedule(x["due"], x["msg"], x.get("banner", True), x.get("stale", 0))
    if IS_HUB:                                    # IA-2 week: exam reminders on the room speaker (exams.py)
        import exams
        n = exams.arm(lambda s, m: _add_reminder(s, m, banner=False, stale=exams.STALE), pending)
        if n: print("[reminder] armed %d exam reminders" % n, flush=True)

CLIP_DIR = os.path.expanduser("~/Developer/youtube/clipper")   # Mac only (post_watch.py announces from there)

def clip_submitted() -> str:
    """'Nova, submitted': mark the last announced clip post submitted in posts.json (only that field). Never submits anything."""
    import re as _re
    pf, af = os.path.join(CLIP_DIR, "posts.json"), os.path.join(CLIP_DIR, ".announced.json")
    if not os.path.exists(pf): return "I can only mark clips from the Mac, sir."
    try: ann = json.load(open(af))
    except (OSError, ValueError): ann = {}
    posts = {str(p["id"]): p for p in json.load(open(pf))}
    todo = sorted((a["first"], i) for i, a in ann.items() if i in posts and not posts[i].get("submitted"))
    if not todo: return "Nothing waiting to be marked, sir."
    pid = todo[-1][1]                                            # the most recently announced one
    s = open(pf).read()
    s2 = _re.sub(r'(\{[^{}]*"id": %s,[^{}]*"submitted": )false' % pid, r"\1true", s, count=1)   # keep the file's layout
    if s2 == s: return "Couldn't find that post in the file, sir."
    tmp = pf + ".tmp"; open(tmp, "w").write(s2); os.replace(tmp, pf)
    return "Marked submitted: the %s clip." % posts[pid].get("campaign", "")

def next_exam() -> str:
    """Next IA-2 exam: subject, day, time and how long until it."""
    import exams
    return exams.next_exam()

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
        c.disconnect(); c.loop_stop()   # this order: loop_stop() first sat out the loop's 1 s select -> every peek took 1 s
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
    except Exception: swallowed()

def dev_last():
    try: return json.load(open(DEV_FILE))
    except Exception: return {}


def _ac_echo(msgs, wait=2.5):
    """Publish AC commands; True once the ESP32 publishes a fresh (non-retained) AC state = it heard us."""
    got = threading.Event(); c = mqtt_client()
    c.on_message = lambda cl, u, m: m.retain or got.set()
    c.connect(_IOT_BROKER, 1883, 5); c.loop_start()
    try:
        c.subscribe("home/room/ac", qos=1); time.sleep(0.3)      # retained copy arrives first and is ignored
        for t, p in msgs:
            c.publish(t, p, qos=1).wait_for_publish(3)
        return got.wait(wait)
    finally:
        c.disconnect(); c.loop_stop()


_broker_kicked = [0.0]
def _broker_restart():
    """Restart the hub's MQTT broker (at most once per 10 min) and wait for the room ESP32 to come back. False = skipped."""
    if time.time() - _broker_kicked[0] < 600: return False
    _broker_kicked[0] = time.time()
    kick = "launchctl kickstart -k gui/$(id -u)/com.nova.broker"
    subprocess.run(["sh", "-c", kick] if IS_HUB else ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "nova-hub", kick],
                   capture_output=True, timeout=20)
    print("[ac] room node deaf -> restarted the MQTT broker", flush=True)
    for _ in range(30):                   # ESP32 reconnects + resubscribes within a few seconds
        time.sleep(1)
        try:
            if _mqtt_peek(["home/room/status"]).get("home/room/status") == "online": time.sleep(1); return True
        except Exception: swallowed()
    return True


def ac(command: str, routine: bool = False) -> str:
    """Control the LG AC through the room ESP32's IR LED (LG protocol, 2026-11-10). IR is one-way: "AC on." means sent, not obeyed.
    command e.g. 'on', 'off', 'temp 24', 'mode cool', 'fan high', 'increase', 'decrease', 'status'."""
    _dev("ac", command)
    cmd = (command or "").lower().strip()
    if not routine and cmd not in ("", "status"):     # you changed it yourself -> the hub drops pending scheduled AC
        try: _hub_send("ac_manual", str(time.time()))   # steps (goodnight's 26 overrode a manual 21, 2026-11-17)
        except Exception: swallowed()
    # "temp 21 for 5 min" -> do it, then put the AC back the way it was after N minutes
    m = re.search(r"\s*\bfor\s+(\d+(?:\.\d+)?)\s*(h|hrs?|hours?|m|mins?|minutes?)\b", cmd)
    if m:
        mins = float(m.group(1)) * (60 if m.group(2).startswith("h") else 1)
        try:
            prev = (_mqtt_peek(["home/room/ac"]).get("home/room/ac") or "off 24").split()
        except Exception:
            prev = ["off", "24"]
        revert = "off" if prev[0] == "off" else "temp " + prev[1]
        said = ac(cmd[:m.start()] + cmd[m.end():])
        # via the hub's "later" queue (even on the hub itself) so the revert survives a restart
        _hub_send("later", json.dumps({"name": "ac timer", "st": {"do": "ac", "arg": revert, "after_min": mins}}))
        back = "off" if revert == "off" else "back to %s degrees" % prev[1]
        return "%s For %g minute%s, then %s." % (said, mins, "" if mins == 1 else "s", back)
    try:
        st = _mqtt_peek(["home/room/status", "home/room/ac"])
    except Exception:
        st = {}
    if st.get("home/room/status") != "online":    # the Tuya blaster was removed 2026-11-20: the room ESP32 is the only path
        return "The room node is offline, so I can't reach the AC."
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
        if not _ac_echo(_pub_set):        # 2026-11-20: the ESP32 was online + publishing but deaf to every /set
            if not _broker_restart():      # (lost MQTT subscription); a broker restart makes it resubscribe
                return "The room node isn't responding, and I restarted its connection recently, sir. Try unplugging it."
            if not _ac_echo(_pub_set):
                return "The room node isn't taking commands even after a reconnect, sir. Try unplugging it."
            print("[ac] room node was deaf -> broker restarted, command went through", flush=True)
    except Exception as e:
        return "The AC didn't respond: %s" % str(e)[:60]
    return say

def ensure_panel():
    """Start light_panel (the BLE strips' server) if it isn't running. True = just started it.
    Runs as a child of hub Nova so it inherits NovaHub.app's Bluetooth permission (a launchd job wouldn't)."""
    import urllib.request, subprocess
    try: urllib.request.urlopen("http://localhost:8099/state", timeout=0.4); return False
    except Exception: swallowed()
    subprocess.Popen([sys.executable, os.path.expanduser("~/anish-ai/light_panel.py")], start_new_session=True,
                     stdout=open(os.path.expanduser("~/anish-ai/light_panel.log"), "a"), stderr=subprocess.STDOUT)
    return True

def lights(command: str, mirror: bool = True) -> str:
    """Control the BLE LED strip (local Bluetooth). command e.g. 'on','off','blue','warm','brightness 60'.
    mirror=False (routine steps): strips only; the ceiling bulb keeps what the routine set it to."""
    _dev("lights", command)
    import os, sys
    sys.path.insert(0, os.path.expanduser("~/anish-ai"))
    if not IS_HUB:   # the strip is Bluetooth -> only the hub (next to it) can reach it
        try: _hub_send("lights" if mirror else "strips", command)   # ponytail: no ack from the hub; add a reply topic if it matters
        except Exception as e: return f"Couldn't reach the hub for the lights: {e}"
        return f"Lights {command}, sir."
    if ensure_panel(): time.sleep(6)
    from lights import lights as _lights
    said = _lights(command)          # the panel sends it to every strip (bed + table)
    try:                             # ceiling bulb follows the same mode (colour/warm/party/on/off); routines set its brightness themselves
        import wiz
        if mirror and not re.search(r"bright|dim|speed", command.lower()) and wiz.parse(command):
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
    subprocess.run(["open", url + "/panel"])
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
            swallowed()
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
_proj_lock = threading.Lock()

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
    """Star projector via IR (Tuya blaster). action: on|off|toggle|colour|brighter|dimmer|faster|slower|timer|reset.
    'is on' / 'is off' = the owner says what it really is (remote used / IR missed): only update memory, press nothing."""
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
    m = re.fullmatch(r"(?:it'?s|is|was|already|its)\s+(?:already\s+)?(on|off)", a)
    if m:                                          # memory fix only: the power button is a toggle, so pressing would undo it
        if m.group(1) == "on": open(_PROJ_ON, "w").close()
        elif os.path.exists(_PROJ_ON): os.remove(_PROJ_ON)
        return "Got it, I'll remember the projector is %s, sir." % m.group(1)
    with _proj_lock:                               # two routines at once both read "on" and pressed the toggle twice
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
            except Exception: swallowed()
        elif val != "":                              # real ESP32 sends per-topic values
            data[key] = val
    c = mqtt_client()
    c.on_message = on_msg
    try:
        c.connect(_IOT_BROKER, 1883, 5)
        c.subscribe(f"home/{_IOT_ROOM}/#")           # telemetry + individual sensor/actuator topics
        c.loop_start(); _time.sleep(1.0); c.disconnect(); c.loop_stop()   # retained values land in ~0.1 s
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
    except FileNotFoundError:
        pass                                   # no Claude session yet (normal on the hub)
    except Exception:
        swallowed()
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
        swallowed()
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
    except Exception: swallowed()
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
         "play_music": play_music, "stop_music": stop_music, "play_playlist": play_playlist, "next_song": next_song, "pause_music": pause_music, "pick_song": pick_song, "camera_mic": camera_mic, "next_exam": next_exam, "clip_submitted": clip_submitted, "run_command": run_command,
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
        "name": "play_music", "description": "Play a song, artist, or album by name (streams audio from YouTube). Use this when a song/artist/album IS named ('play Dark Red'); no name given -> pick_song. Never use shell commands for music.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Song / artist / album to play, e.g. '500 Miles'"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "stop_music", "description": "Stop the music that is currently playing.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "play_playlist", "description": "Play a playlist song by song. No url = the user's own playlist ('play my playlist').",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "YouTube / YouTube Music playlist link; empty for the user's playlist"},
            "shuffle": {"type": "boolean", "description": "true if the user asked for shuffle"}}}}},
    {"type": "function", "function": {
        "name": "next_song", "description": "Skip to the next song ('next', 'skip this song').",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "next_exam", "description": "The user's next exam (IA-2 this week): subject, when, and time left. Use for 'what's my next exam', 'when is my next exam', 'how long until my exam'.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "camera_mic", "description": "Privacy switch for the room camera and/or microphones ('camera off', 'mic off', 'camera and mic off', 'camera on').",
        "parameters": {"type": "object", "properties": {
            "device": {"type": "string", "enum": ["camera", "mic", "both"]},
            "action": {"type": "string", "enum": ["on", "off"]}}, "required": ["device", "action"]}}},
    {"type": "function", "function": {
        "name": "pause_music", "description": "Pause or resume the music ('pause', 'resume', 'play/pause'). Toggles.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "pick_song", "description": "The user wants music but named NO song, artist or playlist ('play a song', 'play something', 'play music'): open the song picker on the Mac.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "set_volume", "description": "Set the volume: a number 0-100, or 'up'/'down' for louder/quieter ('volume up', 'turn it down').",
        "parameters": {"type": "object", "properties": {
            "level": {"type": "string", "description": "0-100, 'up', 'down', or a change like '+20'"}}, "required": ["level"]}}},
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
            "command": {"type": "string", "description": "e.g. 'on', 'off', 'temp 24', 'temp 21 for 5 min', 'increase', 'decrease', 'mode cool', 'fan high'"}}, "required": ["command"]}}},
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
        swallowed()

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
