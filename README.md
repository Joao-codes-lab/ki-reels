# ki-reels

Automatische Kurzvideos im Format „Die 8 Level von …“ für TikTok und Instagram Reels (Deutsch + Englisch).

Ablauf (täglich per GitHub Actions, `.github/workflows/daily.yml`):
1. `reels/scriptgen.py` – Thema wählen, Skript pro Sprache mit Gemini (Ausweich: Groq) schreiben
2. `reels/tts.py` – Sprecherstimme mit Wortzeiten (edge-tts)
3. `reels/render.py` – eigene Grafiken, Level-Leiter, Untertitel, MP4 1080×1920
4. GitHub Pages hostet die Videos, `reels/buffer.py` plant sie über die Buffer-API ein

Lokal testen: `python make_video.py content/de_chatgpt_level.json --tts espeak`

Secrets: `GEMINI_API_KEY` (optional `GROQ_API_KEY`), `BUFFER_KEY_DE`, `BUFFER_KEY_EN`. Einrichtung: siehe `SETUP.md`.
