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
            tokens=os.path.join(D, "base.en-tokens.txt"), language="en", task="transcribe", num_threads=2)   # 2 real cores: 4 was ~20% slower (0.79 vs 0.65 s)
    return _rec


VAD_F = os.path.join(os.path.dirname(D), "silero_vad.onnx")
VAD_THR = 0.3   # calibration knob. Owner's clips 2026-11-20: 0.3 kept 29/29 "Nova" + 54/55 speech, skipped 8/20 noise
_vad = None


def has_speech(pcm, rate=16000):
    """Silero VAD (~0.03 s) before Whisper (~1 s on the hub): 59% of clips were noise that Whisper ran on for nothing.
    pcm = the volume-normalised int16 clip Whisper gets (raw quiet clips fooled the VAD). No model -> True."""
    global _vad
    if not os.path.exists(VAD_F):
        return True
    import sherpa_onnx
    if _vad is None:
        c = sherpa_onnx.VadModelConfig(); c.sample_rate = rate; c.num_threads = 1
        c.silero_vad.model, c.silero_vad.threshold = VAD_F, VAD_THR
        c.silero_vad.min_silence_duration, c.silero_vad.min_speech_duration = 0.25, 0.2
        _vad = sherpa_onnx.VoiceActivityDetector(c, buffer_size_in_seconds=30)
    x = np.asarray(pcm, np.float32) / 32768.0
    _vad.reset()
    for i in range(0, len(x), 512):
        _vad.accept_waveform(x[i:i + 512])
    _vad.flush(); found = not _vad.empty()
    while not _vad.empty(): _vad.pop()
    return found


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
        if os.path.exists(VAD_F):          # VAD: the sample is speech, silence/hiss is not
            q = a.astype(np.float32); q = np.clip(q * 2000.0 / (np.sqrt(np.mean(q ** 2)) or 1), -32768, 32767).astype(np.int16)
            hiss = (np.random.default_rng(0).normal(0, 2000, 32000)).astype(np.int16)
            assert has_speech(q) and not has_speech(np.zeros(32000, np.int16)) and not has_speech(hiss)
        print("localstt ok")
