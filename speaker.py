"""Who is talking? Voice "fingerprint" (speaker embedding, CAM++ via sherpa-onnx, all local).
Conversation mode uses it: the voice that said "Nova" is the only voice whose follow-ups count, so the TV and
other people in the room are ignored without anyone having to enrol."""
import os
import numpy as np

MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "spk_campp_en.onnx")
SAME = 0.50          # cosine >= this = same person. 2026-11-12 data: you 0.85, video/noise <= 0.48
ENFORCE = False      # 2026-11-12: soft voice at the bed mic scored 0.40-0.51 vs video 0.23-0.41 -> overlap, it blocked
                    # the owner. Log + keep clips only; turn on when voice_samples/ shows a clean gap.
REF_MIN_S = 2.0      # a reference voice built from less than this ("Nova?" = 1.1 s) is too weak to reject on
MIN_S = 0.8          # shorter clips give unreliable fingerprints -> "unknown" (None)
_ext = None


def _extractor():
    global _ext
    if _ext is None:
        import sherpa_onnx
        _ext = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=MODEL, num_threads=2))
    return _ext


def voiced(pcm, gate, rate=16000):
    """Only the 80 ms frames louder than gate (the speech): silence/room noise would fingerprint the room."""
    pcm = np.asarray(pcm, np.int16); n = int(rate * 0.08); k = pcm.size // n
    if not k: return pcm[:0]
    fr = pcm[:k * n].reshape(k, n)
    return fr[np.sqrt((fr.astype(np.float32) ** 2).mean(1)) >= gate].reshape(-1)


def embed(pcm, rate=16000, gate=None):
    """int16 mono PCM -> unit vector, or None if too little speech / no model. gate: keep only frames this loud."""
    pcm = np.asarray(pcm)
    if gate is not None:
        pcm = voiced(pcm, gate, rate)
    if pcm.size < MIN_S * rate or not os.path.exists(MODEL):
        return None
    ext = _extractor()
    s = ext.create_stream()
    s.accept_waveform(rate, (pcm.astype(np.float32) / 32768.0).tolist())
    s.input_finished()
    if not ext.is_ready(s):
        return None
    v = np.array(ext.compute(s), np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_samples")   # git-ignored, stays on the hub
KEEP = 60            # newest clips kept per folder


def keep(pcm, kind, sc=None, rate=16000, cap=KEEP):
    """Save a clip for tests/calibration: voice_samples/<kind>/<time>_<score>.wav; kind = wake | you | other."""
    import time, wave
    pcm = np.asarray(pcm, np.int16)
    if pcm.size < 0.3 * rate:
        return
    d = os.path.join(SAMPLES, kind); os.makedirs(d, exist_ok=True)
    w = wave.open(os.path.join(d, "%s_%s.wav" % (time.strftime("%Y%m%d-%H%M%S"), "na" if sc is None else "%.2f" % sc)), "wb")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm.tobytes()); w.close()
    for old in sorted(os.listdir(d))[:-cap]:
        os.remove(os.path.join(d, old))


def score(a, b):
    """Cosine similarity of two embeddings; None if either is unknown."""
    return None if a is None or b is None else float(np.dot(a, b))


if __name__ == "__main__":       # self-check / calibration: python speaker.py a.wav b.wav ... (pairwise scores)
    import sys, wave, itertools
    def load(p):
        w = wave.open(p)
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16)
        if w.getnchannels() > 1: a = a.reshape(-1, w.getnchannels())[:, 0]
        if w.getframerate() != 16000:        # crude resample is fine for a fingerprint
            a = np.interp(np.arange(0, len(a), w.getframerate() / 16000), np.arange(len(a)), a).astype(np.int16)
        return a
    if len(sys.argv) > 2:
        es = {os.path.basename(p): embed(load(p)) for p in sys.argv[1:]}
        for (na, a), (nb, b) in itertools.combinations(es.items(), 2):
            s = score(a, b); print("%.2f  %s  %s" % (s if s is not None else -9, na, nb))
        sys.exit()
    rng = np.random.default_rng(0)
    assert embed(np.zeros(4000, np.int16)) is None                       # too short -> unknown
    x = (rng.standard_normal(32000) * 3000).astype(np.int16)
    e = embed(x); assert e is not None and abs(np.linalg.norm(e) - 1) < 1e-3
    assert score(e, e) > 0.99 and score(e, None) is None
    quiet_then_loud = np.concatenate([np.full(48000, 50, np.int16), x])          # 3 s room + 2 s "speech"
    assert abs(voiced(quiet_then_loud, 1000).size / 16000 - 2.0) < 0.1          # counts speech, not clip length
    assert embed(np.full(48000, 50, np.int16), gate=1000) is None               # all room noise -> unknown
    import tempfile
    SAMPLES = tempfile.mkdtemp(); KEEP = 3
    for i in range(5):
        keep(x, "you", 0.5 + i / 100)
    import time as _t; files = os.listdir(os.path.join(SAMPLES, "you"))
    assert 1 <= len(files) <= 3, files                                  # rotation keeps the newest only
    print("speaker ok")
