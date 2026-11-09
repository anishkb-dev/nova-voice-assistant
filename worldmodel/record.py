#!/usr/bin/env python3
"""
World-model data recorder: camera frames + the action in force at each frame.

  python3 ~/anish-ai/worldmodel/record.py              # drive with the phone/keyboard, Ctrl-C to stop
  python3 ~/anish-ai/worldmodel/record.py --cam 192.168.68.114
  python3 ~/anish-ai/worldmodel/record.py --selftest

Each run -> worldmodel/data/<timestamp>/
  frames/000001.jpg ...   raw frames as the camera sent them
  log.csv                 frame, t, throttle(-1/0/1), steer(-100..100), speed(0-100), dist_cm, vbat

The action for a frame mirrors the firmware: a throttle/steer command only counts for `pulse` ms
after it was sent (the phone re-sends every 200ms while held), after that the car has auto-stopped.
"""
import csv, os, sys, time, threading, urllib.request
import paho.mqtt.client as mqtt

HERE = os.path.dirname(os.path.abspath(__file__))
state = {"thr": 0, "thr_t": 0.0, "steer": 0, "steer_t": 0.0, "speed": 45, "pulse": 0.6,
         "dist": -1.0, "vbat": 0.0}
lock = threading.Lock()


def split_jpegs(buf):
    """Pull complete JPEGs (SOI..EOI) out of an MJPEG byte stream. Returns (frames, leftover)."""
    frames = []
    while True:
        a = buf.find(b"\xff\xd8")
        if a < 0: return frames, b""
        b = buf.find(b"\xff\xd9", a + 2)
        if b < 0: return frames, buf[a:]
        frames.append(buf[a:b + 2]); buf = buf[b + 2:]


def steer_val(p):
    if p == "left": return -100
    if p == "right": return 100
    try: return max(-100, min(100, int(p)))
    except ValueError: return 0   # "center" / junk


def on_msg(c, u, m):
    p, now = m.payload.decode(errors="ignore").strip(), time.time()
    k = m.topic.rsplit("/", 1)[-1]
    with lock:
        if k == "throttle": state["thr"] = {"forward": 1, "back": -1}.get(p, 0); state["thr_t"] = now
        elif k == "steer":  state["steer"] = steer_val(p); state["steer_t"] = now
        elif k == "speed":  state["speed"] = int(p) if p.isdigit() else state["speed"]
        elif k == "pulse":  state["pulse"] = int(p) / 1000 if p.isdigit() else state["pulse"]
        elif k == "distance":
            try: state["dist"] = float(p)
            except ValueError: pass
        elif k == "battery":
            try: state["vbat"] = float(p)
            except ValueError: pass


def action_now(now):
    with lock:
        live = lambda t: state["pulse"] == 0 or now - t <= state["pulse"]   # pulse 0 = latched
        return (state["thr"] if live(state["thr_t"]) else 0,
                state["steer"] if live(state["steer_t"]) else 0,
                state["speed"], state["dist"], state["vbat"])


def record(cam):
    run = os.path.join(HERE, "data", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(os.path.join(run, "frames"))
    try: c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError: c = mqtt.Client()
    c.on_message = on_msg
    c.connect("localhost", 1883, 10)
    c.subscribe("home/car/#"); c.loop_start()

    n, t0 = 0, time.time()
    with open(os.path.join(run, "log.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["frame", "t", "throttle", "steer", "speed", "dist_cm", "vbat"])
        print(f"recording {cam} -> {run}   (Ctrl-C to stop)")
        try:
            while True:
                try:
                    s, buf = urllib.request.urlopen(f"http://{cam}:81/stream", timeout=5), b""
                    while True:
                        chunk = s.read(4096)
                        if not chunk: break
                        frames, buf = split_jpegs(buf + chunk)
                        for jpg in frames:
                            now = time.time(); n += 1
                            with open(os.path.join(run, "frames", f"{n:06d}.jpg"), "wb") as im: im.write(jpg)
                            w.writerow([n, f"{now:.3f}", *action_now(now)])
                            if n % 20 == 0:
                                f.flush()
                                sys.stdout.write(f"\r  {n} frames  {n / (now - t0):4.1f} fps  action={action_now(now)[:3]}   ")
                                sys.stdout.flush()
                except OSError as e:   # stream dropped (WiFi hiccup / cam reboot): note it and reconnect
                    print(f"\n  stream error: {e} — reconnecting"); time.sleep(1)
        except KeyboardInterrupt:
            dt = time.time() - t0
            print(f"\nsaved {n} frames in {dt:.0f}s ({n / max(dt, 1):.1f} fps) -> {run}")
    c.loop_stop()


def selftest():
    a, b = b"\xff\xd8AAA\xff\xd9", b"\xff\xd8BB\xff\xd9"
    fr, rest = split_jpegs(b"--frame\r\n" + a + b"\r\n--frame\r\n" + b[:3])
    assert fr == [a] and rest == b[:3], (fr, rest)
    fr, rest = split_jpegs(rest + b[3:])
    assert fr == [b] and rest == b""
    assert [steer_val(x) for x in ("left", "right", "center", "-40", "250")] == [-100, 100, 0, -40, 100]
    state.update(thr=1, thr_t=100.0, steer=-100, steer_t=100.0, pulse=0.6)
    assert action_now(100.5)[:2] == (1, -100)    # inside the pulse window: command in force
    assert action_now(100.7)[:2] == (0, 0)       # past it: car has auto-stopped
    print("selftest PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv: selftest()
    else: record(sys.argv[sys.argv.index("--cam") + 1] if "--cam" in sys.argv else "192.168.68.114")
