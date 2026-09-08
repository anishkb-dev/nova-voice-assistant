#!/usr/bin/env python3
"""Owner face recognition for Jarvis — ArcFace embeddings via insightface (onnxruntime, no torch).

  python3 face_id.py enroll   # sit in front of the camera to register YOUR face (do this once)
  python3 face_id.py check    # test whether it recognizes you right now
"""
import os, sys, time
import numpy as np

OWNER = os.path.expanduser("~/anish-ai/owner_face.npy")
THRESH = 0.35            # cosine similarity above this = it's the owner (ArcFace/buffalo_s)

_APP = None
def _app():
    global _APP
    if _APP is None:
        from insightface.app import FaceAnalysis
        a = FaceAnalysis(name="buffalo_s", allowed_modules=["detection", "recognition"],
                         providers=["CPUExecutionProvider"])
        a.prepare(ctx_id=-1, det_size=(320, 320))   # ctx_id=-1 -> CPU
        _APP = a
    return _APP

def _largest_face(frame):
    faces = _app().get(frame)
    if not faces:
        return None
    return max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))

def _open_cam(idx=None):
    import cv2
    if idx is None:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from gesture_volume import pick_camera
            idx = pick_camera()
        except Exception:
            idx = None
    if idx is None:
        return None                      # no external webcam -> never use the Mac built-in
    print("using camera index %d" % idx, flush=True)
    return cv2.VideoCapture(idx)

def enroll(n=25, show=True, idx=None):
    import cv2
    cap = _open_cam(idx)
    if cap is None:
        print("No external webcam found — plug in the Lapcare and try again.", flush=True); return False
    embs = []
    print("Look at the camera... capturing %d samples (press q to finish/abort)" % n, flush=True)
    win = "Face Enrollment  -  face the camera, press q when done"
    tries = 0
    while len(embs) < n and tries < n * 14:
        tries += 1
        ok, f = cap.read()
        if not ok:
            continue
        face = _largest_face(f)
        if face is not None:
            embs.append(face.normed_embedding)
        if show:
            if face is not None:
                x1, y1, x2, y2 = [int(v) for v in face.bbox]
                cv2.rectangle(f, (x1, y1), (x2, y2), (0, 255, 0), 3)
            col = (0, 255, 0) if face is not None else (40, 40, 255)
            cv2.putText(f, "Captured %d/%d %s" % (len(embs), n, "" if face is not None else "- NO FACE (fix lighting/angle)"),
                        (24, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.9, col, 2)
            cv2.imshow(win, f)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        else:
            if face is not None:
                print("  %d/%d" % (len(embs), n), flush=True)
            time.sleep(0.04)
    cap.release()
    if show:
        cv2.destroyAllWindows()
    if len(embs) < 5:
        print("Not enough face samples — make sure your face is well-lit, centered, and not backlit.", flush=True)
        return False
    mean = np.mean(embs, axis=0); mean = mean / np.linalg.norm(mean)
    np.save(OWNER, mean)
    print("Enrolled owner face (%d samples) -> %s" % (len(embs), OWNER), flush=True)
    return True

def is_owner(timeout=2.5):
    """True = owner recognized, False = a face that isn't the owner, None = not enrolled / no face seen.
    Uses ONLY the configured camera (the Lapcare) — never the Mac built-in."""
    if not os.path.exists(OWNER):
        return None
    owner = np.load(OWNER)
    cap = _open_cam()                             # external webcam only (None if unplugged)
    if cap is None:
        return None
    best = -1.0; saw_face = False; t0 = time.time()
    while time.time() - t0 < timeout:
        ok, f = cap.read()
        if not ok:
            continue
        face = _largest_face(f)
        if face is not None:
            saw_face = True
            best = max(best, float(np.dot(owner, face.normed_embedding)))
            if best >= THRESH:
                break
    cap.release()
    if not saw_face:
        return None
    return best >= THRESH

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    forced = int(sys.argv[2]) if len(sys.argv) > 2 else None
    if cmd == "enroll":
        enroll(idx=forced)
    else:
        print("owner?", is_owner())
