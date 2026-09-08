#!/usr/bin/env python3
"""JARVIS doctor — one-shot health check of every subsystem.

    python3 ~/anish-ai/doctor.py

Prints PASS / WARN / FAIL for: python deps, API keys, the brain, the mic,
the AC (Tuya IR blaster), the smart room (MQTT + ESP32), face recognition,
and the running JARVIS process (+ recent errors in its log). Run it from the
Terminal (not an IDE) so the mic check has microphone permission.
"""
import os, sys, subprocess, json, time

HOME = os.path.expanduser("~")
AI = os.path.join(HOME, "anish-ai")
sys.path.insert(0, AI)
G, Y, R, DIM, RST = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"
OK, WARN, BAD = 0, 0, 0

def line(status, name, detail=""):
    global OK, WARN, BAD
    mark = {"ok": G + "  ✓ PASS", "warn": Y + "  ⚠ WARN", "bad": R + "  ✗ FAIL"}[status]
    OK += status == "ok"; WARN += status == "warn"; BAD += status == "bad"
    print("%s%s  %-22s%s %s%s" % (mark, RST, name, DIM, detail, RST))

def head(t):
    print("\n\033[1m" + t + RST)

# ---------- python deps ----------
head("Dependencies")
for mod, need in [("pyaudio", True), ("numpy", True), ("requests", True), ("noisereduce", False),
                  ("paho.mqtt.client", True), ("tinytuya", False), ("edge_tts", True),
                  ("insightface", False), ("cv2", False), ("ollama", False)]:
    try:
        __import__(mod)
        line("ok", mod)
    except Exception as e:
        line("bad" if need else "warn", mod, "missing — " + str(e)[:40])

# ---------- API keys ----------
head("API keys")
def key(name):
    try:
        k = open(os.path.join(AI, ".%s_key" % name)).read().strip()
        return "" if (not k or "PASTE" in k.upper()) else k
    except Exception:
        return ""
for k in ("groq", "claude", "nvidia"):
    line("ok" if key(k) else "warn", "%s key" % k, "set" if key(k) else "not set")

# ---------- brain ----------
head("Brain (Groq)")
gk = key("groq")
if not gk:
    line("bad", "brain", "no groq key -> falls back to local ollama only")
else:
    try:
        import requests
        t = time.time()
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                          headers={"Authorization": "Bearer " + gk},
                          json={"model": "qwen/qwen3.8-27b",
                                "messages": [{"role": "user", "content": "reply with the single word: ok"}],
                                "max_tokens": 20}, timeout=15)
        if r.ok:
            c = (r.json()["choices"][0]["message"].get("content") or "").strip()
            line("ok" if c else "warn", "qwen3.8-27b", "%.1fs reply=%r" % (time.time() - t, c[:30]))
        else:
            line("bad", "qwen3.8-27b", "HTTP %s %s" % (r.status_code, r.text[:60]))
    except Exception as e:
        line("bad", "qwen3.8-27b", str(e)[:50])

# ---------- mic ----------
head("Microphone")
try:
    import pyaudio, numpy as np
    pa = pyaudio.PyAudio()
    ins = [(i, pa.get_device_info_by_index(i)["name"]) for i in range(pa.get_device_count())
           if pa.get_device_info_by_index(i).get("maxInputChannels", 0) > 0]
    line("ok" if ins else "bad", "input devices", ", ".join(n for _, n in ins) or "none")
    idx = next((i for i, n in ins if "macbook" in n.lower() or "built-in" in n.lower()),
               ins[0][0] if ins else None)
    _jarvis_up = subprocess.run(["pgrep", "-f", "jarvis_app.py"], capture_output=True).returncode == 0
    if _jarvis_up:                                # don't grab the mic out from under a running JARVIS
        line("warn", "capture level", "skipped — JARVIS is holding the mic. Stop it first to level-test.")
    elif idx is not None:
        s = pa.open(rate=16000, channels=1, format=pyaudio.paInt16, input=True,
                    input_device_index=idx, frames_per_buffer=1280)
        peak = 0.0
        for _ in range(30):                       # ~2.4s: speak during this for a real reading
            a = np.frombuffer(s.read(1280, exception_on_overflow=False), dtype=np.int16).astype(np.float32)
            peak = max(peak, float(np.sqrt(np.mean(a ** 2))))
        s.close()
        st = "ok" if peak > 120 else ("warn" if peak > 30 else "bad")
        line(st, "capture level", "peak rms=%.0f  (speak while it runs; <30 = silence/no permission)" % peak)
    pa.terminate()
except Exception as e:
    line("bad", "mic", str(e)[:60])

# ---------- AC (Tuya) ----------
head("Air conditioner (Tuya IR)")
try:
    import tinytuya
    conf = json.load(open(os.path.join(HOME, "tinytuya.json")))
    c = tinytuya.Cloud(apiRegion=conf["apiRegion"], apiKey=conf["apiKey"],
                       apiSecret=conf["apiSecret"], apiDeviceID=conf["apiDeviceID"])
    IR = conf.get("infrared_id", "")   # device ids kept in ~/tinytuya.json (git-ignored, outside repo)
    r = c.cloudrequest("/v1.0/devices/%s" % IR)
    online = r.get("result", {}).get("online")
    line("ok" if online else "bad", "IR blaster", "online" if online else "OFFLINE (check its WiFi/power)")
    st = c.cloudrequest("/v2.0/infrareds/%s/remotes/%s/ac/status" % (IR, conf.get("remote_id", "")))
    if st.get("success"):
        line("ok", "AC endpoint", "reachable, last state=%s" % st.get("result"))
    else:
        line("warn", "AC endpoint", st.get("msg", "?"))
except Exception as e:
    line("bad", "tuya/AC", str(e)[:60])

# ---------- smart room (MQTT + ESP32) ----------
head("Smart room (MQTT + ESP32)")
broker_up = subprocess.run(["pgrep", "-x", "mosquitto"], capture_output=True).returncode == 0
line("ok" if broker_up else "bad", "mosquitto", "running" if broker_up else "NOT running")
if broker_up:
    try:
        import paho.mqtt.client as mqtt
        got = {}
        def on_msg(cl, u, m): got[m.topic.split("/")[-1]] = m.payload.decode()
        try:
            cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except Exception:
            cl = mqtt.Client()
        cl.on_message = on_msg
        cl.connect("localhost", 1883, 5); cl.subscribe("home/room/#"); cl.loop_start()
        time.sleep(2.5); cl.loop_stop(); cl.disconnect()
        esp = got.get("status")
        line("ok" if esp == "online" else "bad", "ESP32", "online" if esp == "online" else "offline / not seen")
        if got:
            line("ok", "relays", "light=%s fan=%s plug=%s" % (got.get("light", "?"), got.get("fan", "?"), got.get("plug", "?")))
            line("ok", "sensors", "temp=%s humidity=%s motion=%s" % (got.get("temp", "?"), got.get("humidity", "?"), got.get("motion", "?")))
        else:
            line("warn", "topics", "no retained home/room/* messages")
    except Exception as e:
        line("bad", "mqtt", str(e)[:60])

# ---------- face ----------
head("Face recognition")
line("ok" if os.path.exists(os.path.join(AI, "owner_face.npy")) else "warn", "owner enrolled",
     "yes" if os.path.exists(os.path.join(AI, "owner_face.npy")) else "no — run: python3 face_id.py enroll")

# ---------- running process + recent errors ----------
head("JARVIS process")
pids = subprocess.run(["pgrep", "-f", "jarvis_app.py"], capture_output=True, text=True).stdout.split()
line("ok" if pids else "warn", "process", "running (pid %s)" % pids[0] if pids else "not running")
log = "/tmp/jarvis.log"
if os.path.exists(log):
    txt = open(log, "rb").read().decode("utf-8", "ignore")
    armed = "[hf] listening (" in txt
    line("ok" if armed else "warn", "listener armed", "yes" if armed else "not yet / hung")
    errs = [l for l in txt.splitlines()[-300:] if ("Traceback" in l or "loop fatal" in l or "MIC FAIL" in l
            or "chat error" in l)]   # only recent; 429s are transient rate-limits, not faults
    line("ok" if not errs else "warn", "recent errors", "none" if not errs else "%d — %s" % (len(errs), errs[-1][:60]))

# ---------- summary ----------
print("\n\033[1mSummary:%s %s%d pass%s  %s%d warn%s  %s%d fail%s" %
      (RST, G, OK, RST, Y, WARN, RST, R, BAD, RST))
print(DIM + "Tip: live view -> tail -f /tmp/jarvis.log   (voice lines start with [hf])" + RST)
