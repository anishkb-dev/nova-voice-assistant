#!/usr/bin/env python3
"""Gesture volume control for Jarvis — pinch thumb+index to set macOS volume.

Port of hennyanandwani/gesture-based-volume-control-python to macOS:
that repo uses pycaw (Windows-only) for the volume; here it's `osascript`.

Run:  python3 gesture_volume.py         (opens webcam window; 'q' to quit)
Test: python3 gesture_volume.py --test  (no camera, checks the mapping)

Distance is normalised by palm size (wrist->index-knuckle) so it works at any
camera distance. If the mapping feels off, tune RATIO_MIN/RATIO_MAX below.
"""
import subprocess, sys, time, os

# --- auto-calibration: maps YOUR observed min/max stretch to 0..100 volume ---
CLAMP_LO, CLAMP_HI = 0.2, 3.5   # ignore impossible ratios (mis-detections)
MIN_SPAN = 0.3                  # explore at least this much range before mapping full-scale
DEADBAND = 3                    # ignore volume jitter smaller than this so holding still stays put
LOCK_FRAMES = 12                # ~0.6s with the hand out of view -> lock and stop adjusting
VOL_FILE = os.path.join(os.path.dirname(__file__), ".vol_state")  # HUD reads this for a synced bar


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def ratio_to_volume(ratio, lo, hi):
    """Map ratio within the observed [lo, hi] stretch range -> 0..100, clamped."""
    if hi - lo < 1e-6:
        return 0
    frac = (ratio - lo) / (hi - lo)
    return max(0, min(100, round(frac * 100)))


def set_volume(v):
    # Popen (not run) — don't block the video loop waiting on osascript (~40ms each).
    subprocess.Popen(["osascript", "-e", f"set volume output volume {int(v)}"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def hand_pose(lm, w, h):
    """Return (upright, fingers_extended) for the 4 non-thumb fingers.
    upright = hand pointing up (middle tip above wrist)."""
    pt = lambda i: (lm[i].x * w, lm[i].y * h)
    upright = pt(12)[1] < pt(0)[1]          # middle-finger tip above wrist
    up = sum(1 for tip, pip in [(8, 6), (12, 10), (16, 14), (20, 18)]
             if pt(tip)[1] < pt(pip)[1] - 5)  # tip above its knuckle -> finger extended
    return upright, up


def palm_openness(wlm):
    """Rotation-INVARIANT openness from MediaPipe 3D world landmarks (metric).
    3D pairwise distances are unchanged by hand rotation (rotation preserves distances) --
    only finger curl changes them. mean of (fingertip->wrist / knuckle->wrist). ~0.9 fist, ~1.8 open."""
    d = lambda a, b: ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2) ** 0.5
    wrist = wlm[0]
    return sum(d(wlm[tip], wrist) / (d(wlm[mcp], wrist) or 1e-6)
               for tip, mcp in [(8, 5), (12, 9), (16, 13), (20, 17)]) / 4




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
    """Return the index of the EXTERNAL webcam (e.g. the Lapcare), or None if none is plugged in.
    NEVER returns (or even opens) the Mac built-in: we first check for an external via system_profiler
    WITHOUT powering any camera on, and only probe camera indices when one is actually connected."""
    import cv2, numpy as np, os, json
    if not _external_present():                  # no external webcam -> don't open ANY camera (no blinking)
        print("gesture camera: no external webcam plugged in", flush=True)
        return None
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
    print("gesture camera: no external webcam plugged in", flush=True)
    return None


def run():
    import os, cv2, mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    # Python 3.14 mediapipe ships only the Tasks API (no legacy mp.solutions), so use HandLandmarker.
    model = os.path.join(os.path.dirname(__file__), "hand_landmarker.task")
    opts = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=model),
        num_hands=1, min_hand_detection_confidence=0.7,
        running_mode=vision.RunningMode.VIDEO)   # VIDEO tracks between frames -> far faster than IMAGE
    landmarker = vision.HandLandmarker.create_from_options(opts)
    def open_cam():
        idx = pick_camera()                      # external webcam only (None if unplugged -> never the Mac cam)
        if idx is None:
            return None
        c = cv2.VideoCapture(idx)
        c.set(cv2.CAP_PROP_FRAME_WIDTH, 320); c.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)  # low res -> faster inference, less lag
        return c
    cap = open_cam()
    # Coalescing setter: the loop only stores the latest target; this thread applies it with a
    # BLOCKING osascript (so calls never pile up). A fast sweep drops intermediates instead of
    # queueing 100 processes -> the audio tracks the hand instead of trailing a backlog.
    import threading
    target = {"v": None}
    def _apply():
        cur = None
        while True:
            v = target["v"]
            if v is not None and v != cur:
                subprocess.run(["osascript", "-e", f"set volume output volume {v}"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                cur = v
            else:
                time.sleep(0.008)
    threading.Thread(target=_apply, daemon=True).start()
    last, ts, active = -1, 0, False
    lo = hi = sm = None                     # observed openness range + smoothed value
    nohand = 0                               # frames with no hand in view -> triggers lock
    print("gesture watcher running (headless). Show an open upright palm to activate.", flush=True)
    bad = 0
    while True:
        if os.getppid() == 1:               # parent Jarvis died (reparented to launchd) -> exit, free the camera
            break
        if cap is None or not cap.isOpened():   # no external webcam plugged in -> wait for it, never use the Mac cam
            time.sleep(8); cap = open_cam(); continue   # 8s: light system_profiler poll, no camera powered on
        ok, frame = cap.read()
        # macOS sleep kills the capture; on wake read() fails or returns black frames forever.
        # Detect that and reopen the camera so gesture control survives sleep/wake.
        if not ok or frame is None or frame.mean() < 1:
            bad += 1
            if bad >= 15:
                cap.release(); time.sleep(1.0); cap = open_cam(); bad = 0
                print("camera reopened (sleep/wake recovery)", flush=True)
            else:
                time.sleep(0.1)
            continue
        bad = 0
        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB,
                          data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        ts += 33                            # strictly-increasing ms timestamp VIDEO mode requires
        res = landmarker.detect_for_video(mp_img, ts)
        if res.hand_landmarks:
            nohand = 0
            lm = res.hand_landmarks[0]
            wlm = res.hand_world_landmarks[0] if res.hand_world_landmarks else None
            upright, fingers = hand_pose(lm, w, h)
            if upright and fingers >= 4 and not active:     # open upright palm = turn ON
                active, lo, hi, sm = True, None, None, None
                print("gesture control ON — open/close your palm for volume, drop your hand to lock", flush=True)
            # only read volume when the WHOLE hand is well inside the frame. As you move it toward
            # the edge to drop it, this goes False -> updates freeze -> it locks at the pre-drop value.
            xs = [p.x for p in lm]; ys = [p.y for p in lm]
            in_view = 0.07 < min(xs) and max(xs) < 0.93 and 0.07 < min(ys) and max(ys) < 0.93
            if active and in_view and wlm is not None:      # openness (rotation-invariant) sets the volume
                o = palm_openness(wlm)
                sm = o if sm is None else 0.5 * o + 0.5 * sm   # smoothing (snap handles the extremes)
                lo = sm if lo is None else min(lo, sm)       # widen range as you open/close
                hi = sm if hi is None else max(hi, sm)
                if hi - lo >= MIN_SPAN:                      # enough range -> full open=100, fist=0
                    vol = ratio_to_volume(sm, lo, hi)
                    if vol >= 92: vol = 100                  # snap extremes: full-open reliably hits 100,
                    elif vol <= 8: vol = 0                   # and a fist reliably hits 0
                    if vol != last and (abs(vol - last) >= DEADBAND or vol in (0, 100)):
                        target["v"] = vol; last = vol
                        try:                                 # let the HUD bar track this instantly
                            with open(VOL_FILE, "w") as fh: fh.write(f"{vol},{time.time()}")
                        except Exception: pass
        elif active:                                        # hand out of view -> lock after ~0.6s (keeps the value)
            nohand += 1
            if nohand >= LOCK_FRAMES:
                active = False; print(f"locked at {last}% (hand removed)", flush=True)
        if not active:
            time.sleep(0.08)                # idle at ~10fps to save CPU until a palm shows up
    if cap is not None:                      # may be None if no webcam was ever plugged in
        cap.release()


def _test():
    lo, hi = 0.6, 2.4
    assert ratio_to_volume(lo, lo, hi) == 0        # least stretch -> 0
    assert ratio_to_volume(hi, lo, hi) == 100      # full stretch -> 100
    assert ratio_to_volume(0.0, lo, hi) == 0       # clamps below
    assert ratio_to_volume(99, lo, hi) == 100      # clamps above
    assert 48 <= ratio_to_volume((lo + hi) / 2, lo, hi) <= 52
    assert ratio_to_volume(1.0, 1.0, 1.0) == 0     # zero span -> no crash
    assert dist((0, 0), (3, 4)) == 5.0
    # hand_pose: build 21 fake landmarks (y small = top of image)
    from types import SimpleNamespace
    def hand(tips_y):                              # tips_y: y for tips 8,12,16,20
        pts = [SimpleNamespace(x=0.5, y=0.5) for _ in range(21)]
        pts[0].y = 0.9                             # wrist near bottom
        for i, (tip, pip) in enumerate([(8, 6), (12, 10), (16, 14), (20, 18)]):
            pts[pip].y = 0.5; pts[tip].y = tips_y[i]
        return pts
    assert hand_pose(hand([0.3, 0.25, 0.3, 0.35]), 100, 100) == (True, 4)   # open palm
    assert hand_pose(hand([0.6, 0.6, 0.6, 0.6]), 100, 100) == (True, 0)     # fist
    # palm_openness (3D world landmarks): open > fist, AND invariant to hand rotation
    import math
    def h3(ext):                                   # ext: finger extension factor (2=open, ~1=fist)
        pts = [SimpleNamespace(x=0.0, y=0.0, z=0.0) for _ in range(21)]
        mcps = {5: (-0.3, 0, 1), 9: (0, 0, 1.1), 13: (0.3, 0, 1), 17: (0.5, 0, 0.9)}
        for i, (x, y, z) in mcps.items(): pts[i].x, pts[i].y, pts[i].z = x, y, z
        for tip, mcp in [(8, 5), (12, 9), (16, 13), (20, 17)]:
            m = pts[mcp]; pts[tip].x, pts[tip].y, pts[tip].z = m.x * ext, m.y * ext, m.z * ext
        return pts
    assert palm_openness(h3(2.0)) > palm_openness(h3(1.0))       # open > fist
    def rot(pts, a):                               # rotate all points about the y-axis
        c, s = math.cos(a), math.sin(a)
        return [SimpleNamespace(x=c * p.x + s * p.z, y=p.y, z=-s * p.x + c * p.z) for p in pts]
    assert abs(palm_openness(h3(2.0)) - palm_openness(rot(h3(2.0), 1.2))) < 1e-9   # rotation-invariant
    print("ok")


if __name__ == "__main__":
    (_test if "--test" in sys.argv else run)()
