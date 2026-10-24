# ki-reels

Automatische Kurzvideos im Format „Die 8 Level von …“ für TikTok und Instagram Reels (Deutsch + Englisch).

Ablauf (täglich per GitHub Actions, `.github/workflows/daily.yml`):
1. `reels/scriptgen.py` – Thema wählen, Skript pro Sprache mit Gemini (Ausweich: Groq) schreiben
2. `reels/tts.py` – Sprecherstimme mit Wortzeiten (edge-tts)
3. `reels/render.py` – eigene Grafiken, Level-Leiter, Untertitel, MP4 1080×1920
4. GitHub Pages hostet die Videos, `reels/buffer.py` plant sie über die Buffer-API ein

Trend-Scout (samstags, `.github/workflows/trends.yml`): `tools/trend_scout.py` sucht meistgesehene englische Shorts
(Suchbegriffe in `data/trend_queries.json`), zerlegt Hook/Aufbau/Spannung mit Gemini und legt daraus eigene deutsche
Serienthemen vorne in `data/series_topics.json` an. Der Bauplan (`data/blueprints.json`) fließt in das Serienskript ein;
übernommen wird nur die Mechanik, nie Text oder Bilder. Bericht: `data/adaptations/<datum>.md`.

Lokal testen: `python make_video.py content/de_chatgpt_level.json --tts espeak`

Secrets: `GEMINI_API_KEY` (optional `GROQ_API_KEY`), `BUFFER_KEY_DE`, `BUFFER_KEY_EN`. Einrichtung: siehe `SETUP.md`.
