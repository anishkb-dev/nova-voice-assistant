"""Room guard (runs on the hub while the Mac is away): webcam motion -> photo to your Telegram.

  python guard.py setup   # after saving the bot token to ~/anish-ai/.telegram_key and pressing Start in the bot
  python guard.py test    # send a test photo
  python guard.py         # offline self-check of the motion logic
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_F = os.path.join(HERE, ".telegram_key")      # git-ignored (*_key)
CHAT_F = os.path.join(HERE, ".telegram_chat_key")  # guard stays off until setup writes this
SENT_LOG = os.path.join(HERE, ".tg_sent.jsonl")     # git-ignored: what the bot sent you (morning read-out)
MOTION_PCT = 2.0     # % of pixels that must change; raise if curtains/light flicker trigger it
COOLDOWN = 120       # s between alerts, so one visitor isn't 50 messages


def _tg(method, **kw):
    import requests
    tok = open(TOKEN_F).read().strip()
    r = requests.post(f"https://api.telegram.org/bot{tok}/{method}", timeout=20, **kw)
    r.raise_for_status()
    if method in ("sendMessage", "sendPhoto"):          # remember what the bot told you -> read out at good morning
        try:
            import json
            text = (kw.get("data") or {}).get("text") or (kw.get("data") or {}).get("caption") or ""
            with open(SENT_LOG, "a") as f:
                f.write(json.dumps({"ts": time.time(), "text": text[:500]}) + "\n")
        except Exception:
            pass
    return r.json()


def sent_since(ts):
    """Messages the bot sent after unix time ts, oldest first (from this machine's log)."""
    import json
    try:
        rows = [json.loads(l) for l in open(SENT_LOG)]
    except Exception:
        return []
    return [r for r in rows if r.get("ts", 0) > ts and r.get("text")]


def send_text(text):
    return _tg("sendMessage", data={"chat_id": open(CHAT_F).read().strip(), "text": text})


def send_photo(jpg_bytes, caption):
    chat = open(CHAT_F).read().strip()
    return _tg("sendPhoto", data={"chat_id": chat, "caption": caption},
               files={"photo": ("room.jpg", jpg_bytes, "image/jpeg")})


def changed_pct(prev, cur):
    """% of pixels that changed between two blurred grayscale frames."""
    import cv2, numpy as np
    d = cv2.absdiff(prev, cur)
    return 100.0 * np.count_nonzero(d > 25) / d.size


def _prep(frame):
    import cv2
    g = cv2.cvtColor(cv2.resize(frame, (320, 180)), cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(g, (21, 21), 0)


def _cam():
    import cv2
    sys.path.insert(0, HERE)
    from cam_presence import pick_camera
    return cv2.VideoCapture(pick_camera())


def watch(should_run, log=print):
    """Watch the webcam while should_run() is True; on motion send a photo. Releases the camera on exit."""
    import cv2
    cap = _cam()
    prev, last_alert = None, 0.0
    log("[guard] watching the room")
    try:
        while should_run():
            ok, frame = cap.read()
            if not ok:
                time.sleep(1); continue
            cur = _prep(frame)
            if prev is not None and changed_pct(prev, cur) > MOTION_PCT and time.time() - last_alert > COOLDOWN:
                time.sleep(0.8)                              # let them step into frame
                for _ in range(5): ok, frame = cap.read()   # flush stale buffered frames
                jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
                try:
                    send_photo(jpg, "Someone is in your room — " + time.strftime("%a %d %b, %I:%M %p"))
                    log("[guard] motion -> photo sent")
                except Exception as e:
                    log("[guard] couldn't send alert: %s" % str(e)[:80])
                last_alert = time.time()
            prev = cur
            time.sleep(0.5)                                   # ~2 fps is plenty, keeps the old CPU cool
    finally:
        cap.release()
        log("[guard] stopped")


def setup():
    """Find your chat id from the Start you pressed in the bot, and save it."""
    ups = _tg("getUpdates").get("result", [])
    chats = [u["message"]["chat"] for u in ups if "message" in u]
    if not chats:
        sys.exit("No messages yet. Open your bot in Telegram, press Start / send 'hi', then rerun setup.")
    c = chats[-1]
    open(CHAT_F, "w").write(str(c["id"])); os.chmod(CHAT_F, 0o600)
    _tg("sendMessage", data={"chat_id": c["id"], "text": "Nova room guard linked. You'll get a photo here if someone enters while you're away."})
    print("linked to chat", c.get("username") or c.get("first_name"), c["id"])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "setup":
        setup()
    elif cmd == "test":
        import cv2
        cap = _cam()
        for _ in range(10): ok, f = cap.read()
        cap.release()
        print(send_photo(cv2.imencode(".jpg", f)[1].tobytes(), "Nova guard test photo")["ok"])
    else:   # self-check: still scene -> no motion, a person-sized block -> motion
        import numpy as np
        a = np.full((180, 320, 3), 90, np.uint8); b = a.copy(); b[40:160, 100:180] = 200
        assert changed_pct(_prep(a), _prep(a)) < MOTION_PCT
        assert changed_pct(_prep(a), _prep(b)) > MOTION_PCT
        print("guard motion checks passed")
