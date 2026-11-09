#!/usr/bin/env python3
"""Room presence from the hub webcam (replaced gesture volume control 2026-11-10: it cost ~22% CPU).

Once a second, diff two tiny blurred frames; any real change (typing, shifting, a head turn) touches
SEEN_FILE, whose mtime the automation rules use as "someone's here" alongside the PIR.

Run:  python3 cam_presence.py          (Nova starts/stops it via nova.gesture_control)
Test: python3 cam_presence.py --test   (no camera)
Tune: kill -USR1 <pid> dumps the last 2 min of change % to /tmp/nova_cam_pcts
"""
import collections, os, signal, subprocess, sys, time

SEEN_FILE = "/tmp/nova_cam_seen"  # mtime = last time the camera saw movement; content = that change %
MOVE_PCT = 0.1                    # % pixels changed between 1 s frames = someone there (empty room reads 0.00)
MAC_CAM = 0                       # "MacBook Air Camera"


def _external_present():
    """True if a real external USB/UVC webcam is connected (not the Mac built-in or iPhone).
    Uses system_profiler, which does NOT power on any camera — so no blinking indicator light."""
    import subprocess
    try:
        out = subprocess.run(["system_profiler", "SPCameraDataType"],
                             capture_output=True, text=True, timeout=8).stdout
    except Exception:
        return True                              # can't tell -> allow probing
    return ("VendorID" in out) or ("USB Camera" in out)


def pick_camera():
    """Return the index of the EXTERNAL webcam (e.g. the Lapcare); if none is plugged in, the Mac built-in."""
    import cv2, numpy as np, os, json
    if not _external_present():                  # no external webcam -> fall back to the Mac built-in
        print("gesture camera: no external webcam -> using Mac camera (index %d)" % MAC_CAM, flush=True)
        return MAC_CAM
    try:
        builtin = tuple(json.load(open(os.path.expanduser("~/anish-ai/camera.json"))).get("builtin_res", []))
    except Exception:
        builtin = ()
    for i in range(3):
        cap = cv2.VideoCapture(i)
        if not cap.isOpened():
            cap.release(); continue
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)); frame = None
        for _ in range(10):                      # warm up
            ok, f = cap.read()
            if ok and f is not None: frame = f
        cap.release()
        if frame is None or float(frame.mean()) < 5:     # dead/black feed
            continue
        b, g, r = frame[:, :, 0].astype(int), frame[:, :, 1].astype(int), frame[:, :, 2].astype(int)
        if (abs(b - g).mean() + abs(g - r).mean()) / 2 < 3:   # grayscale -> not the webcam
            continue
        if builtin and (w, h) == builtin:        # the Mac built-in (and iPhone, same res) -> never use it
            continue
        print("gesture camera: external webcam at index %d (%dx%d)" % (i, w, h), flush=True)
        return i
    print("gesture camera: no external webcam -> using Mac camera (index %d)" % MAC_CAM, flush=True)
    return MAC_CAM


def moved_pct(prev, cur):
    """% of pixels that changed between two tiny blurred grayscale frames."""
    import cv2
    return float((cv2.absdiff(cur, prev) > 12).mean() * 100)


def run():
    import cv2
    def open_cam():
        idx = pick_camera()
        if idx is None:
            return None
        c = cv2.VideoCapture(idx)
        c.set(cv2.CAP_PROP_FRAME_WIDTH, 320); c.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        return c
    cap, prev, bad = open_cam(), None, 0
    pcts = collections.deque(maxlen=120)
    def _dump(*_):
        try: open("/tmp/nova_cam_pcts", "w").write(" ".join(map(str, pcts)))
        except Exception: pass
    signal.signal(signal.SIGUSR1, _dump)
    print("camera presence running", flush=True)
    while os.getppid() != 1:                     # parent Nova died -> exit, free the camera
        if cap is None or not cap.isOpened():
            time.sleep(8); cap = open_cam(); continue
        cap.grab(); ok, frame = cap.read()       # grab() drops a buffered frame so we diff "now"
        if not ok or frame is None or frame.mean() < 1:   # sleep/wake leaves a dead capture -> reopen
            bad += 1
            if bad >= 15:
                cap.release(); time.sleep(1); cap = open_cam(); bad = 0
            time.sleep(0.2); continue
        bad = 0
        g = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(frame, (80, 60)), cv2.COLOR_BGR2GRAY), (5, 5), 0)
        if prev is not None:
            pct = moved_pct(prev, g); pcts.append(round(pct, 2))
            if pct >= MOVE_PCT:
                try:
                    with open(SEEN_FILE, "w") as fh: fh.write("%.2f" % pct)
                except Exception: pass
        prev = g
        time.sleep(1)
    if cap is not None:
        cap.release()


if __name__ == "__main__":
    if "--test" in sys.argv:
        import numpy as np
        a = np.zeros((60, 80), np.uint8); b = a.copy(); b[10:30, 10:40] = 200
        assert moved_pct(a, a) == 0 and moved_pct(a, b) >= MOVE_PCT
        print("ok")
    else:
        run()
