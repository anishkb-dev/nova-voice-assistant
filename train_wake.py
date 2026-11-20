"""Train the "Nova" wake-word detector on the hub, all local (openWakeWord features + a small sklearn classifier).
Positives: voice_samples/nova (recording mode). Test: voice_samples/wake (older real wakes, never trained on).
Run on the hub:  ~/nova-venv/bin/python train_wake.py   -> models/nova_wake.pkl + a test report."""
import glob, os, pickle, subprocess, sys, tempfile, wave
import numpy as np
from openwakeword.utils import AudioFeatures

R, WIN = 16000, 32000                  # 2 s of audio -> 16 embedding frames (~1.3 s) = one classifier input
D = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(D, "voice_samples")
OUT = os.path.join(D, "models", "nova_wake.pkl")
THR = 0.7                              # calibration knob: 0.9 = fewer false wakes, more misses
TV = {"20261112-070109_na.wav"}         # a "Nova" clip that was really the TV ("Now what will you do")
F = AudioFeatures(inference_framework="onnx")


def load(f):
    w = wave.open(f); return np.frombuffer(w.readframes(w.getnframes()), np.int16)


def norm(p):                           # same loudness as live (transcribe() normalises to RMS 2000)
    x = p.astype(np.float32); x *= min(2000 / (np.sqrt(np.mean(x ** 2)) or 1), 30000 / (np.abs(x).max() or 1))
    return np.clip(x, -32768, 32767).astype(np.int16)


def windows(p, ends):
    """(n, 16*96) features for the 2 s windows ending at sample offsets `ends`."""
    p = np.concatenate([np.zeros(WIN, np.int16), norm(p)])
    clips = np.stack([p[e:e + WIN] for e in ends])      # e is shifted by the WIN of zero padding
    return F.embed_clips(clips, batch_size=64).reshape(len(ends), -1)


def all_windows(p, hop=0.16):
    return windows(p, [int(t * R) for t in np.arange(0.6, len(p) / R + 1e-9, hop)] or [len(p)])


def onset(p):                          # first frame clearly above the clip's quiet level = speech starts
    fr = p[:len(p) // 1280 * 1280].reshape(-1, 1280).astype(np.float32); e = np.sqrt((fr ** 2).mean(1))
    hot = np.nonzero(e > max(2.5 * np.percentile(e, 20), 40))[0]
    return int(hot[0]) * 1280 if hot.size else 0


def say_clips(lines):
    """Hub's built-in voices saying lines (hard negatives: 'no what' etc.). Local, no download."""
    voices = [v.split()[0] for v in subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout.splitlines()
              if "en_" in v and len(v.split()[0]) > 2][:12]
    out = []; t = tempfile.mkdtemp()
    for i, (v, s) in enumerate((v, s) for v in voices for s in lines):
        a, b = os.path.join(t, "%d.aiff" % i), os.path.join(t, "%d.wav" % i)
        if subprocess.run(["say", "-v", v, "-o", a, s], capture_output=True).returncode: continue
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", a, b], capture_output=True)
        out.append(load(b))
    subprocess.run(["rm", "-rf", t]); return out


SOUNDALIKE = ["No, what is it?", "Now what?", "You know what, forget it", "No matter what", "Over time it changed",
              "No way", "Know what I mean", "Novel idea", "No, wait a minute", "Nowhere to go", "Nobody knows",
              "Turn off the lights", "What time is it?", "Play some music", "Not now", "Hello there", "Nevermind"]


def build(neg_files, pos_files):
    X, y = [], []
    for f in pos_files:
        p = load(f); o = onset(p)
        X.append(windows(p, [min(len(p), o + int(s * R)) for s in (0.55, 0.7, 0.85, 1.0)])); y += [1] * 4
        tail = [e for e in range(o + int(2.2 * R), len(p) + 1, int(0.32 * R))]   # well after "Nova": the rest of the command
        if o > 0.8 * R: tail.append(o)                                            # pre-roll only: the room before you spoke
        if tail: X.append(windows(p, tail)); y += [0] * len(tail)
    for p in neg_files:
        w = all_windows(p); X.append(w); y += [0] * len(w)
    return np.vstack(X), np.array(y)


def score(clf, p):                     # live-like: best window anywhere in the clip
    return float(clf.predict_proba(all_windows(p))[:, 1].max())


if __name__ == "__main__":
    import localstt
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    pos = [f for f in sorted(glob.glob(S + "/nova/*.wav")) if localstt.has_speech(norm(load(f)))]
    quiet = [load(f) for f in sorted(glob.glob(S + "/nova/*.wav")) if f not in pos]
    you = sorted(glob.glob(S + "/you/*.wav"))
    bg = [load(f) for f in sorted(glob.glob("/tmp/nova_stt/*.wav")) if os.path.exists(f)]
    syn = say_clips(SOUNDALIKE)
    neg_train = quiet + bg + [load(f) for f in you[::2]] + syn[::2]
    test_pos = [f for f in sorted(glob.glob(S + "/wake/*.wav")) if os.path.basename(f) not in TV]
    test_neg = ([load(f) for f in sorted(glob.glob(S + "/other/*.wav")) + you[1::2]] + [load(S + "/wake/" + t) for t in TV
                if os.path.exists(S + "/wake/" + t)] + syn[1::2])
    X, y = build(neg_train, pos)
    print("train: %d positive clips -> %d windows, %d negative windows" % (len(pos), y.sum(), (y == 0).sum()), flush=True)
    # older wake clips predate the 18 Nov mic filter (they sound different): reported, not used to pick
    clf = make_pipeline(StandardScaler(), LogisticRegression(C=0.05, class_weight="balanced", max_iter=3000)).fit(X, y)
    groups = {"other voices": [load(f) for f in sorted(glob.glob(S + "/other/*.wav"))], "your non-Nova speech": [load(f) for f in you[1::2]],
              "computer-voice sound-alikes": syn[1::2], "older Nova clips": [load(f) for f in test_pos]}
    for g, clips in groups.items():
        sc = [score(clf, p) for p in clips]
        print("%-28s %d clips, over %.1f: %d" % (g, len(sc), THR, sum(x >= THR for x in sc)), flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    pickle.dump({"clf": clf, "thr": THR}, open(OUT, "wb")); print("saved", OUT)
