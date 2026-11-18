"""Nova supervisor (hub, launchd com.nova.supervisor). Its own process, so it keeps running while Nova is off.

Watches: Nova app, voice loop, bed mic, camera, broker, room ESP32 (AC/sensors), BLE strip panel, WiZ bulb,
hub power and disk. Telegram once when something has been down a while (with a Fix button where one exists),
once when it's back. Bottom keyboard in the bot: Status / Nova off / Nova on.

It is the ONLY getUpdates poller for the bot: two pollers steal each other's button taps.

    python supervisor.py check   # print one round of checks and exit
"""
import json, os, shutil, socket, subprocess, sys, threading, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guard, wiz

CHAT = open(guard.CHAT_F).read().strip()
OFF_F = os.path.join(HERE, ".nova_off")              # exists = you turned Nova off (survives reboots)
PLIST = os.path.expanduser("~/Library/LaunchAgents/com.nova.app.plist")
DOM = "gui/%d" % os.getuid()
KEYBOARD = {"keyboard": [[{"text": "📊 Status"}], [{"text": "🔴 Nova off"}, {"text": "🟢 Nova on"}],
                       [{"text": "🙈 Cam+mic off"}, {"text": "👁 Cam+mic on"}]],
            "resize_keyboard": True, "is_persistent": True}
# com.nova.app runs `open -W -a NovaHub.app`: killing the job leaves the app up, so kill Nova itself (launchd relaunches it)
RESTART_NOVA = ("Restart Nova", "pkill -f 'app/nova_app[.]py'; pkill -f 'cam_presence[.]py'")
FIXES = {"broker": ("Restart broker", "launchctl kickstart -k %s/com.nova.broker" % DOM),
         **{k: RESTART_NOVA for k in ("nova", "voice", "camera", "strips")}}
MICS = {"bedmic": ("Bed mic", "esp32-bedmic.local"), "tablemic": ("Table mic", "esp32-room.local")}
room = {"online": None}
mq = {"c": None}


def pub_off():
    """Retained home/nova/off: the Mac's Nova pauses its mic while it's 1 (broker restarts drop it, so on connect too)."""
    try: mq["c"] and mq["c"].publish("home/nova/off", "1" if nova_off() else "0", retain=True)
    except Exception: pass                              # home/room/status, kept by the MQTT thread


def tg(method, **data):
    """Bot call that is NOT logged to the morning read-out (guard._tg logs every message)."""
    tok = open(guard.TOKEN_F).read().strip()
    r = requests.post("https://api.telegram.org/bot%s/%s" % (tok, method), data=data, timeout=40)
    r.raise_for_status()
    return r.json()


def red(e):
    """Error text without the bot token (a failed Telegram call prints its URL)."""
    return str(e).replace(open(guard.TOKEN_F).read().strip(), "<token>")[:160]


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)


def nova_off():
    return os.path.exists(OFF_F)


def running(pattern):
    return sh("pgrep -f '%s'" % pattern).returncode == 0   # [.] so the pattern can't match this shell's own command line


def heartbeat():
    try:
        hb = json.load(open("/tmp/nova_hb.json"))
        return hb if time.time() - hb["ts"] < 120 else None
    except Exception:
        return None


def checks():
    """key -> (label, problem text or None, wait-before-alert s, fix (button, cmd) or None). Nova's parts skip when off."""
    out = {}
    def add(key, label, bad, after=180):
        out[key] = (label, bad, after, FIXES.get(key))
    try: socket.create_connection(("127.0.0.1", 1883), timeout=2).close(); broker = None
    except OSError: broker = "not answering on :1883"
    add("broker", "MQTT broker", broker, 120)
    add("room", "Room ESP32 (AC + sensors)", None if room["online"] else "offline", 300)
    try:
        p = requests.get("http://127.0.0.1:8099/state", timeout=3).json()
        strips = None if p.get("connected") else "strips not connected"
    except Exception:
        strips = "light panel not running"
    add("strips", "LED strips (BLE)", strips, 300)
    add("bulb", "WiZ bulb", None if wiz.state() else "not answering (wall switch off?)", None)   # Status only, no alert
    batt = sh("pmset -g batt").stdout
    add("power", "Hub power", None if "AC Power" in batt else "ON BATTERY " + (batt.split("\t")[-1].split(";")[0] if "\t" in batt else ""), 60)
    free = shutil.disk_usage("/").free / 2**30
    add("disk", "Hub disk", None if free > 3 else "%.1f GB free" % free, 0)
    if not nova_off():
        app = running("app/nova_app[.]py")
        add("nova", "Nova app", None if app else "not running", 120)
        if app:
            hb = heartbeat()
            add("voice", "Voice (listening)", None if hb and hb["hf"] else ("not listening" if hb else "Nova not responding"), 300)
            try: all_muted = "*" in open(os.path.join(HERE, ".mic_mute")).read().split()   # owner said "mic off"
            except OSError: all_muted = False
            if hb and not all_muted and not os.path.exists(os.path.join(HERE, ".bedmic_off")):
                for key, (label, host) in MICS.items():
                    try: ip = socket.gethostbyname(host)
                    except OSError: ip = None
                    add(key, label, None if ip in hb.get("mics", []) else
                        ("no audio from %s" % ip if ip else "%s not on Wi-Fi (power?)" % host), 300)
            if not os.path.exists(os.path.join(HERE, ".asleep")) and not os.path.exists(os.path.join(HERE, ".camera_off")):   # off on purpose
                add("camera", "Camera (presence)", None if running("cam_presence[.]py") else "not running", 300)
    return out


def status_text():
    lines = ["🔴 Nova is OFF (supervisor still watching)" if nova_off() else "🟢 Nova is ON"]
    for label, bad, _, _ in checks().values():
        lines.append(("❌ %s: %s" % (label, bad)) if bad else "✅ " + label)
    try: lines.append("🏷 " + open(os.path.join(HERE, ".version")).read().strip())   # written by deploy.sh
    except OSError: lines.append("🏷 version unknown (not deployed with deploy.sh)")
    return "\n".join(lines)


def set_nova(on, ac_off=False):
    try: return _set_nova(on, ac_off)
    finally: pub_off()


def _set_nova(on, ac_off):
    if on:
        if os.path.exists(OFF_F): os.remove(OFF_F)
        sh("launchctl enable %s/com.nova.app; launchctl bootstrap %s %s" % (DOM, DOM, PLIST))
        return "🟢 Nova is starting (about a minute)."
    ac = ""
    if ac_off:                                         # before Nova goes: nova.ac knows the IR + Tuya paths
        p = sh("cd %s && %s -c 'import nova; print(nova.ac(\"off\"))'" % (HERE, sys.executable))
        ac = "\nAC: " + ((p.stdout.strip().splitlines() or ["?"])[-1] if p.returncode == 0 else "couldn't turn it off: " + red(p.stderr)[-100:])
    open(OFF_F, "w").write(time.strftime("%F %T"))
    sh("launchctl disable %s/com.nova.app; launchctl bootout %s/com.nova.app; pkill -f 'app/nova_app[.]py'; pkill -f 'cam_presence[.]py'" % (DOM, DOM))
    return ("🔴 Nova is off: no listening, camera, voice, automations, reminders or AC timers.\n"
            "Other devices stay as they are. Tap 🟢 Nova on to bring it back." + ac)


# ---------------- watch loop ----------------
state = {}       # key -> [down since, alerted]


def watch():
    time.sleep(90)                                    # boot grace: Nova takes ~1 min to come up
    while True:
        try:
            if nova_off() and running("app/nova_app[.]py"):   # e.g. right after a reboot: keep it off
                set_nova(False)
            now, cur = time.time(), checks()
            for key in list(state):
                if key not in cur: state.pop(key)       # skipped this round (Nova off) -> forget
            for key, (label, bad, after, fix) in cur.items():
                if after is None: continue                     # shown in Status, never alerted
                st = state.setdefault(key, [None, False])
                if bad:
                    st[0] = st[0] or now
                    if not st[1] and now - st[0] >= after:
                        st[1] = True
                        msg = "⚠️ %s: %s" % (label, bad)
                        if fix:
                            kb = {"inline_keyboard": [[{"text": "🔧 " + fix[0], "callback_data": "fix:" + key},
                                                       {"text": "✖ Ignore", "callback_data": "ign:" + key}]]}
                            guard._tg("sendMessage", data={"chat_id": CHAT, "text": msg, "reply_markup": json.dumps(kb)})
                        else:
                            guard.send_text(msg)
                else:
                    if st[1]: guard.send_text("✅ %s is OK again." % label)
                    st[0], st[1] = None, False
        except Exception as e:
            print("[watch]", red(e), flush=True)
        time.sleep(60)


def mqtt_room():
    import paho.mqtt.client as mqtt
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="nova-supervisor")
    c.username_pw_set("nova", open(os.path.join(HERE, ".mqtt_key")).read().strip())   # same sign-in as nova.mqtt_client
    def on_conn(c, *a):
        c.subscribe("home/room/status"); pub_off()
    c.on_connect = on_conn
    mq["c"] = c
    def on_msg(c, u, m): room["online"] = m.payload == b"online"
    def on_disc(*a): room["online"] = None
    c.on_message, c.on_disconnect = on_msg, on_disc
    while True:
        try:
            c.connect("127.0.0.1", 1883, 30); c.loop_forever(retry_first_connection=True)
        except Exception as e:
            print("[mqtt]", e, flush=True)
        room["online"] = None; time.sleep(10)


# ---------------- Telegram buttons ----------------
pending_off = {"at": 0}


def handle(up):
    if "callback_query" in up:
        cq = up["callback_query"]
        if str(cq["from"]["id"]) != CHAT: return
        kind, _, key = (cq.get("data") or "").partition(":")
        msg = cq.get("message", {})
        reply = "Ignored."
        if kind == "fix":
            fix = FIXES.get(key)
            if not fix or (fix is RESTART_NOVA and nova_off()): reply = "Nova is off; tap 🟢 Nova on instead."
            else:
                p = sh(fix[1])
                reply = "✅ Done: %s." % fix[0] if p.returncode == 0 else "❌ %s failed: %s" % (fix[0], (p.stderr or p.stdout)[-200:])
        elif kind == "off" and time.time() - pending_off["at"] < 120:
            pending_off["at"] = 0
            reply = set_nova(False, ac_off=(key == "ac"))
        elif kind == "off":
            reply = "That confirm expired. Tap 🔴 Nova off again."
        elif kind == "cancel":
            reply = "OK, Nova stays on."
        try: tg("answerCallbackQuery", callback_query_id=cq["id"])
        except Exception: pass
        try: tg("editMessageText", chat_id=CHAT, message_id=msg["message_id"], text=msg.get("text", "") + "\n\n" + reply)
        except Exception: tg("sendMessage", chat_id=CHAT, text=reply)
        return
    m = up.get("message") or {}
    if str(m.get("chat", {}).get("id")) != CHAT: return     # only you
    t = (m.get("text") or "").lower()
    if "status" in t:
        tg("sendMessage", chat_id=CHAT, text=status_text(), reply_markup=json.dumps(KEYBOARD))
    elif "nova off" in t or t == "/off":
        if nova_off(): tg("sendMessage", chat_id=CHAT, text="Nova is already off.", reply_markup=json.dumps(KEYBOARD)); return
        pending_off["at"] = time.time()
        kb = {"inline_keyboard": [[{"text": "Off + AC off", "callback_data": "off:ac"},
                                   {"text": "Off, leave AC", "callback_data": "off:"}],
                                  [{"text": "Cancel", "callback_data": "cancel:"}]]}
        tg("sendMessage", chat_id=CHAT, text="Turn Nova off? Listening (hub and Mac), camera, automations and AC timers stop. "
                                             "Nothing will turn the AC off for you while it's off.",
           reply_markup=json.dumps(kb))
    elif ("mic" in t or "cam" in t) and (t.endswith(" on") or t.endswith(" off")):   # 🙈/👁 buttons, or typed "mic on"
        dev = "both" if "cam" in t and "mic" in t else "camera" if "cam" in t else "mic"
        act = "on" if t.endswith(" on") else "off"
        try: mq["c"].publish("home/hub/privacy", "%s %s" % (dev, act), qos=1); reply = "%s %s." % ({"both": "Camera and mic", "camera": "Camera", "mic": "Mic"}[dev], act)
        except Exception as e: reply = "Couldn't reach Nova: %s" % str(e)[:60]
        tg("sendMessage", chat_id=CHAT, text=reply, reply_markup=json.dumps(KEYBOARD))
    elif "nova on" in t or t == "/on":
        tg("sendMessage", chat_id=CHAT, text="Nova is already on." if not nova_off() and running("app/nova_app[.]py")
           else set_nova(True), reply_markup=json.dumps(KEYBOARD))
    else:
        tg("sendMessage", chat_id=CHAT, text="Buttons: 📊 Status, 🔴 Nova off, 🟢 Nova on, 🙈 Cam+mic off, 👁 Cam+mic on.", reply_markup=json.dumps(KEYBOARD))


def poll():
    offset = None
    while True:
        try:
            r = tg("getUpdates", timeout=25, offset=offset or "",
                   allowed_updates=json.dumps(["message", "callback_query"]))
            for up in r.get("result", []):
                offset = up["update_id"] + 1
                try: handle(up)
                except Exception as e: print("[tg] handle:", red(e), flush=True)
        except Exception as e:
            print("[tg] poll:", red(e), flush=True)
            time.sleep(10)


if __name__ == "__main__":
    threading.Thread(target=mqtt_room, daemon=True).start()
    if sys.argv[1:] == ["check"]:
        time.sleep(3); print(status_text()); sys.exit()
    threading.Thread(target=watch, daemon=True).start()
    try: tg("sendMessage", chat_id=CHAT, text="🛡 Nova supervisor running.", reply_markup=json.dumps(KEYBOARD))
    except Exception as e: print("[tg] hello failed", flush=True)
    poll()
