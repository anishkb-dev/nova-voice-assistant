# Nova free-brain checklist

Nova's router (`router.py`) already works on **Groq + your LM Studio box + Ollama**.
Add these free keys to unlock the other brains. **All free, no credit card.** Each key
goes in its own file in `~/anish-ai/` (git-ignored by the `*_key` rule). After adding
any key, run `python3 router.py` to confirm it's live.

## Already working ✅
- **Groq** — `.groq_key` (present). Fast chat, reasoning, code.
- **LM Studio** — your box at `192.168.68.109:1234`, no key. Private fallback.
- **Ollama** — local `jarvis:latest`, no key. Offline fallback.

## Add these (≈10 min total)

| # | Provider | Get the key | Save it to | Unlocks | Free limit |
|---|---|---|---|---|---|
| 1 | **Google Gemini** (AI Studio) | https://aistudio.google.com/apikey | `~/anish-ai/.gemini_key` | 🎨 design, vision, long docs | persistent free, 15 req/min, 1M ctx |
| 2 | **Cerebras** | https://cloud.cerebras.ai | `~/anish-ai/.cerebras_key` | 🧠 fastest reasoning | ~2,000+ tok/s free |
| 3 | **Mistral** | https://console.mistral.ai | `~/anish-ai/.mistral_key` | 💻 Codestral coding | free "Experiment" plan, 1B tok/mo |
| 4 | **OpenRouter** | https://openrouter.ai/keys | `~/anish-ai/.openrouter_key` | 🔀 14 free models (DeepSeek/GLM/Qwen) | 50 req/day, 1M ctx |
| 5 | **SambaNova** *(optional)* | https://cloud.sambanova.ai | `~/anish-ai/.sambanova_key` | overflow capacity | 200k tok/day per model |

**How to save a key** (example):
```bash
echo 'PASTE_YOUR_KEY_HERE' > ~/anish-ai/.gemini_key
python3 ~/anish-ai/router.py     # re-tests every configured brain
```

## After adding keys — verify the model slugs
Model names drift. `router.py` has verified Groq/LM Studio/Ollama slugs, but the
others are best-guess. If a brain shows `FAILED` after you add its key, open its
model list and update the matching entry in the `M = {...}` dict:
- Gemini: https://ai.google.dev/gemini-api/docs/models  (e.g. `gemini-2.5-flash`)
- Cerebras / Mistral / OpenRouter: their model pages (OpenRouter free models end in `:free`).

## Wire the router into Nova
In `jarvis.py` / `app/jarvis_app.py`, replace direct Groq calls with:
```python
from router import chat
reply = chat("fast",   messages)["content"]   # voice chat / intent routing
reply = chat("reason", messages)["content"]   # hard questions
reply = chat("code",   messages)["content"]   # coding tasks
reply = chat("design", messages)["content"]   # generate HTML / artifacts
```
`chat()` returns `{content, tool_calls, provider, model, tried}` and falls back
across providers automatically — so Nova keeps answering even when a free tier
throttles. Tool-calling passes through via `chat(..., tools=TOOLS)`.
