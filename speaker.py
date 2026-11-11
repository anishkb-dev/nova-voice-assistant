"""Who is talking? Voice "fingerprint" (speaker embedding, CAM++ via sherpa-onnx, all local).
Conversation mode uses it: the voice that said "Nova" is the only voice whose follow-ups count, so the TV and
other people in the room are ignored without anyone having to enrol."""
import os
import numpy as np

MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "spk_campp_en.onnx")
SAME = 0.45          # cosine >= this = same person. Tune from "[spk]" lines in nova.log
MIN_S = 0.8          # shorter clips give unreliable fingerprints -> "unknown" (None)
_ext = None


def _extractor():
    global _ext
    if _ext is None:
        import sherpa_onnx
        _ext = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=MODEL, num_threads=2))
    return _ext


def embed(pcm, rate=16000):
    """int16 mono PCM -> unit vector, or None if too short / no model."""
    pcm = np.asarray(pcm)
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
    print("speaker ok")
