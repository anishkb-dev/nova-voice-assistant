"""Nova's voice fingerprint (dad's idea): is the mic hearing Nova's own reply, or a person?
The hub knows exactly what it is playing, so compare the mic's loudness envelope (80 ms frames)
with the played audio's envelope over a range of delays. High correlation -> it's Nova's echo.
Envelopes, not waveforms: room reverb + a 16 kHz mic smear waveforms, but the syllable rhythm survives."""
import io, wave
import numpy as np

FRAME_S = 0.08
ECHO = 0.6          # score >= this = Nova's own voice. Tune from the "[fp]" lines in nova.log


def wav_env(wav_bytes):
    """Loudness per 80 ms of a WAV (what the hub is about to play)."""
    w = wave.open(io.BytesIO(wav_bytes))
    a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)
    if w.getnchannels() > 1:
        a = a.reshape(-1, w.getnchannels()).mean(1)
    n = int(w.getframerate() * FRAME_S); k = len(a) // n
    return np.sqrt((a[:k * n].reshape(k, n) ** 2).mean(1)) if k else np.zeros(0)


def ref_env(segs, t0, n):
    """Played envelope for n frames from wall time t0; segs = [(play_start_time, env)]; 0 = nothing playing."""
    out = np.zeros(n)
    for start, env in segs:
        i = int(round((start - t0) / FRAME_S))
        lo, hi = max(0, i), min(n, i + len(env))
        if lo < hi:
            out[lo:hi] = env[lo - i:hi - i]
    return out


def echo_score(mic_env, segs, t_first, max_lag=20):
    """Best correlation of the mic envelope (first frame starts at wall time t_first) with what Nova played
    0..max_lag frames (~1.6 s: afplay start + speaker->mic + Wi-Fi/buffer) earlier. ~1 = only Nova; low = a person."""
    m = np.log1p(np.asarray(mic_env, float)); n = len(m); best = 0.0
    if m.std() < 1e-6:
        return 0.0
    ref = np.log1p(ref_env(segs, t_first - max_lag * FRAME_S, n + max_lag))
    for lag in range(max_lag + 1):
        r = ref[max_lag - lag:max_lag - lag + n]
        if r.std() > 1e-6:
            best = max(best, float(np.corrcoef(m, r)[0, 1]))
    return best


if __name__ == "__main__":       # self-check: echo scores high, a person scores low, talking over Nova scores low
    rng = np.random.default_rng(1)
    def speech(n):               # syllable-ish bursts: loud 2-4 frames, quiet 1-3
        e = []
        while len(e) < n:
            e += [rng.uniform(800, 3000)] * rng.integers(2, 5) + [rng.uniform(5, 40)] * rng.integers(1, 4)
        return np.array(e[:n])
    nova = speech(60); t0 = 100.0; segs = [(t0, nova)]
    lag = 6                      # mic hears Nova 0.48 s late
    t_first = t0 + 20 * FRAME_S
    echo = 0.15 * nova[20 - lag:45 - lag] + rng.uniform(20, 60, 25)
    you = speech(25) + rng.uniform(20, 60, 25)
    both = echo + speech(25)
    s_echo, s_you, s_both = (echo_score(x, segs, t_first) for x in (echo, you, both))
    assert s_echo > 0.9, s_echo
    assert s_you < ECHO and s_both < ECHO, (s_you, s_both)
    assert echo_score(you, [], t_first) == 0.0        # nothing playing -> never "Nova"
    pcm = (np.sin(np.arange(24000) / 5) * 1000).astype(np.int16).tobytes()
    hdr = io.BytesIO(); w = wave.open(hdr, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
    w.writeframes(pcm); w.close()
    assert len(wav_env(hdr.getvalue())) == 12
    print("echofp ok  echo=%.2f you=%.2f both=%.2f" % (s_echo, s_you, s_both))
