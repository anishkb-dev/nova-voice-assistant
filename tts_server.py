"""Nova's local voice: Kokoro-82M (bm_daniel) on the M4 GPU via MLX.
POST text -> 16-bit 24kHz WAV. Kept loaded so a sentence takes ~0.2-0.9s (first call ever ~10s warm-up).
Run with the MLX venv:  ~/anish-ai/.mlx/bin/python ~/anish-ai/tts_server.py   (nova_app starts it itself)"""
import io
from http.server import BaseHTTPRequestHandler, HTTPServer
import numpy as np, soundfile as sf
from mlx_audio.tts.utils import load_model

VOICE, SPEED, PORT = "bm_daniel", 1.0, 8089
model = load_model("mlx-community/Kokoro-82M-bf16")


def synth(text):
    a = np.concatenate([np.array(r.audio) for r in model.generate(text=text, voice=VOICE, speed=SPEED, lang_code="b")])
    buf = io.BytesIO()
    sf.write(buf, a, 24000, format="WAV", subtype="PCM_16")
    return buf.getvalue()


synth("Good evening, sir.")   # warm-up: the first generate compiles kernels (~10s)


class H(BaseHTTPRequestHandler):
    def do_GET(self):          # health check
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")

    def do_POST(self):
        text = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8", "ignore")
        try:
            body, code = synth(text), 200
        except Exception as e:
            body, code = str(e).encode(), 500
        self.send_response(code)
        self.send_header("Content-Type", "audio/wav"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


HTTPServer(("127.0.0.1", PORT), H).serve_forever()   # single-threaded on purpose: MLX isn't thread-safe
