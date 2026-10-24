"""Legale Musik-Bibliothek nach Stimmung aufbauen (einmalig in GitHub Actions, danach liegt sie im Repo).

  python tools/music_library.py --out research/musik_bib --per-mood 3 --candidates 6

Quelle: Kevin MacLeod / incompetech.com, Lizenz CC BY 4.0 (kommerziell erlaubt, Namensnennung nötig; die passende
Zeile steht in bibliothek.json unter "credit" und gehört in die Caption). Aus dem Katalog (pieces.json) werden pro
Stimmung Kandidaten nach Gefühl, Genre und Tempo vorsortiert, Gemini hört jeden an und bewertet, wie gut er als
Bett unter einer Erzählstimme in dieser Stimmung funktioniert. Die besten landen in <out>/<stimmung>/.
"""
import argparse
import json
import re
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

import deep_analysis as deep

BASE = "https://incompetech.com/music/royalty-free/"
UA = {"User-Agent": "Mozilla/5.0 (ki-reels music library)"}

MOODS = {
    "luxus": {"was": "Reichtum, Luxus, Penthouse, cool und edel, entspannter Groove (Lo-Fi, Lounge, smooth Jazz, Chillhop)",
              "feel": ["bright", "grooving", "relaxed", "calming", "mellow"], "genre": ["jazz", "electronica", "funk", "pop"],
              "bpm": (75, 115)},
    "spannung": {"was": "leise Spannung, Geheimnis, etwas stimmt nicht, pulsierend, ohne Melodie im Vordergrund",
                 "feel": ["suspenseful", "mysterious", "unnerving", "dark", "eerie", "tense"],
                 "genre": ["electronica", "soundtrack", "cinematic"], "bpm": (60, 130)},
    "drama": {"was": "Demütigung, Ungerechtigkeit, Bösewicht hat die Oberhand, schwer und emotional (Trash-TV-Drama)",
              "feel": ["somber", "dark", "intense", "dramatic", "ominous"], "genre": ["soundtrack", "classical", "cinematic"],
              "bpm": (50, 110)},
    "twist": {"was": "Enthüllung, Wendung, Genugtuung, der Underdog gewinnt, großer Aufbau",
              "feel": ["epic", "dramatic", "intense", "action", "driving", "heroic"],
              "genre": ["soundtrack", "rock", "electronica", "cinematic"], "bpm": (90, 150)},
    "gefuehl": {"was": "Traurigkeit, Einsamkeit trotz Reichtum, nachdenklicher Schluss-Satz, Klavier",
                "feel": ["somber", "calming", "sentimental", "melancholy", "romantic", "peaceful"],
                "genre": ["classical", "contemporary", "piano", "soundtrack"], "bpm": (50, 100)},
    "komik": {"was": "Trash-TV-Peinlichkeit, schadenfroh, schräg, leicht komisch", "feel": ["humorous", "bouncy", "quirky", "silly"],
              "genre": ["comedy", "jazz", "world", "pop"], "bpm": (90, 140)},
}

PROMPT = """Hör dir diesen Musiktitel an. Er soll als Hintergrundmusik unter einer deutschen Erzählstimme in einem
70- bis 110-Sekunden-Reel laufen (faceless Comic-Serie über Geld und Status, Vorbild: 8-Levels-Reels und Trash-TV-
Obst-Dramen). Gewünschte Stimmung: {was}.
Antworte NUR mit JSON: {{"passt_1_10": 0, "stimmung": "", "bpm": 0, "stoert_stimme": true, "beste_startsekunde": 0,
"loopbar": true, "warum": ""}}
Bewertung: 10 = sofort einsetzbar, trägt die Stimmung, lässt der Stimme Platz (keine dominante Melodie, kein Gesang)."""


def fetch_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.load(r)


def secs(length):
    try:
        m, s = str(length).split(":")[-2:]
        return int(m) * 60 + int(s)
    except Exception:
        return 0


def rank(pieces, mood):
    cfg = MOODS[mood]
    scored = []
    for p in pieces:
        feel = (p.get("feel") or "").lower()
        genre = (p.get("genre") or "").lower()
        bpm = int(re.sub(r"\D", "", str(p.get("bpm") or "0")) or 0)
        if not p.get("filename") or not 50 <= secs(p.get("length")) <= 330:
            continue
        s = 2 * sum(f in feel for f in cfg["feel"]) + sum(g in genre for g in cfg["genre"])
        s += 1 if cfg["bpm"][0] <= bpm <= cfg["bpm"][1] else 0
        s -= 3 if re.search(r"vocal|voice|choir", (p.get("instruments") or "").lower()) else 0
        if s >= 3:
            scored.append((s, p))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="research/musik_bib")
    ap.add_argument("--per-mood", type=int, default=3)
    ap.add_argument("--candidates", type=int, default=6)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pieces = fetch_json(BASE + "pieces.json")
    print(f"Katalog: {len(pieces)} Titel")
    lib, used = {}, set()
    with tempfile.TemporaryDirectory() as tmp:
        for mood in MOODS:
            tried = []
            for p in [p for p in rank(pieces, mood) if p["filename"] not in used][:a.candidates]:
                mp3 = Path(tmp) / p["filename"]
                try:
                    url = BASE + "mp3-royaltyfree/" + urllib.parse.quote(p["filename"])
                    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                        mp3.write_bytes(r.read())
                    v = deep.gemini_video(mp3, PROMPT.format(was=MOODS[mood]["was"]), mime="audio/mpeg")
                except Exception as e:
                    print(mood, p["title"], "Fehler:", str(e)[:200], flush=True)
                    continue
                score = v.get("passt_1_10", 0) - (3 if v.get("stoert_stimme") else 0)
                tried.append((score, p, v, mp3))
                print(mood, p["title"], p.get("feel"), "->", score, v.get("warum", "")[:120], flush=True)
                time.sleep(6)
            tried.sort(key=lambda x: -x[0])
            lib[mood] = []
            (out / mood).mkdir(exist_ok=True)
            for score, p, v, mp3 in tried[:a.per_mood]:
                shutil.copy(mp3, out / mood / p["filename"])
                used.add(p["filename"])
                lib[mood].append({"file": f"{mood}/{p['filename']}", "title": p["title"], "score": score,
                                  "bpm": p.get("bpm"), "feel": p.get("feel"), "start": v.get("beste_startsekunde", 0),
                                  "loop": v.get("loopbar", True), "warum": v.get("warum"),
                                  "credit": f"Musik: \"{p['title']}\" Kevin MacLeod (incompetech.com), CC BY 4.0"})
    (out / "bibliothek.json").write_text(json.dumps(lib, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({m: [x["title"] for x in v] for m, v in lib.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
