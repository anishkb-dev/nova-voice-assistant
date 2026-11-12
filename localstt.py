"""Unlimited speech-to-text on the hub: Whisper base.en (int8 ONNX via sherpa-onnx), CPU only, no network, no quota.
~0.9 s per command on the 2015 Air; matched Groq on the owner's clips (2026-11-12). Moonshine missed quiet speech,
small.en was 3 s for no gain. transcribe(int16 pcm @16 kHz) -> text; "" for silence/noise."""
import os, re
import numpy as np

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "sherpa-onnx-whisper-base.en")
_rec = None


def available():
    return os.path.exists(os.path.join(D, "base.en-tokens.txt"))


def _recognizer():
    global _rec
    if _rec is None:
        import sherpa_onnx
        _rec = sherpa_onnx.OfflineRecognizer.from_whisper(
            encoder=os.path.join(D, "base.en-encoder.int8.onnx"), decoder=os.path.join(D, "base.en-decoder.int8.onnx"),
            tokens=os.path.join(D, "base.en-tokens.txt"), language="en", task="transcribe", num_threads=4)
    return _rec


def clean(text):
    """Whisper labels non-speech: '(wind blowing)', '[BLANK_AUDIO]', '*music*' -> drop them."""
    return " ".join(re.sub(r"\([^)]*(?:\)|$)|\[[^\]]*(?:\]|$)|\*[^*]*\*|♪+", " ", text).split()).strip()


def transcribe(pcm, rate=16000):
    if not available() or np.asarray(pcm).size < rate * 0.2:
        return ""
    r = _recognizer(); s = r.create_stream()
    s.accept_waveform(rate, np.asarray(pcm, np.float32) / 32768.0)
    r.decode_stream(s)
    return clean(s.result.text)


if __name__ == "__main__":       # self-check on the model's own sample, or: python localstt.py a.wav b.wav
    import sys, time, wave, glob
    assert clean("(wind blowing)") == "" and clean("[BLANK_AUDIO]") == "" and clean("Nova, (cough) lights on") == "Nova, lights on" and clean("(clicking") == "" and clean("(") == ""
    files = sys.argv[1:] or sorted(glob.glob(os.path.join(D, "test_wavs", "*.wav")))[:1]
    for f in files:
        w = wave.open(f); a = np.frombuffer(w.readframes(w.getnframes()), np.int16)
        t = time.time(); txt = transcribe(a, w.getframerate())
        print("%.2fs  %.1fs audio  %s | %s" % (time.time() - t, len(a) / w.getframerate(), os.path.basename(f), txt))
    if not sys.argv[1:]:
        assert len(txt) > 10, txt
        print("localstt ok")
