"""Unabhängige Prüfer: bewerten Skripte und fertige Videos hart und objektiv.

1. Skript-Jury (vor dem Rendern): drei Rollen (Viral-Producer, Zielzuschauer 18-30, Story-Editor)
   bewerten die ganze Serie. Unter 80 Punkten wird die Serie mit dem Feedback überarbeitet (max. 2 Runden).
2. Video-Jury (nach dem Rendern): Gemini schaut und hört das fertige Video und vergibt Punkte.
   Unter VIDEO_MIN Punkten wird das Video nicht gepostet, sondern zurückgehalten.
Alle Bewertungen landen in data/reviews/, damit der Wochenbericht daraus lernen kann.
"""
import base64
import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVIEWS = ROOT / "data" / "reviews"
SERIES_MIN = 85
VIDEO_MIN = int(os.environ.get("VIDEO_MIN", "55"))

JURY_PROMPT = """Ihr seid eine unabhängige, sehr strenge Jury für virale Kurzvideos (TikTok/Instagram Reels).
Rollen: (A) Producer, der täglich Millionen-Reels sieht, (B) typischer Zuschauer 18-30, der nach 2 Sekunden
weiterwischt, wenn ihn nichts packt, (C) Story-Editor. Ihr habt keinen Grund, nett zu sein.

Bewertet diese 8-teilige Serie (ein Teil pro Video) jeweils 0-10:
- hook: Packt der erste Satz jedes Teils sofort?
- story: Echte Geschichte mit Konflikt und Wendung statt Aufzählung?
- identifikation: Erkennt man sich oder Bekannte wieder?
- verbindungen: Gibt es subtile Querverweise zwischen den Figuren, die neugierig machen?
- sog: Gibt es pro Teil EINE offene Frage, auf die das ganze Video hinfiebert und die erst im nächsten Teil
  aufgelöst wird? Will man unbedingt weiterschauen?
- wut: Löst der Bösewicht echte Wut/Empörung aus, sodass man kommentieren will?
- merkfaehigkeit: Bleibt etwas im Kopf (Catchphrase, unverwechselbare Figuren, ein Satz, den man zitiert)?
- sprache: Klingt es gesprochen natürlich, kurz, ohne Floskeln?
Dann: gesamt (0-100) und für jedes schwache Level konkrete Verbesserungen (Satz-genau).

Antworte NUR mit JSON: {{"scores": {{"hook": int, "story": int, "identifikation": int, "verbindungen": int,
"sog": int, "wut": int, "merkfaehigkeit": int, "sprache": int}}, "gesamt": int, "fixes": [{{"n": int, "fix": str}}], "fazit": str}}

SERIE:
{series}"""

REWRITE_PROMPT = """Überarbeite diese Serie anhand der Jury-Kritik. Behalte Thema, Figuren-Grundidee, alle Regeln
und exakt dasselbe JSON-Format (alle Felder, 8 Level, letzter Satz jedes Teils unverändert als
"Das siehst du in Level X." bzw. in der Zielsprache). Setze jede Kritik konkret um.

JURY-KRITIK:
{critique}

SERIE:
{series}"""

VIDEO_PROMPT = """Du bist eine strenge Jury für virale Kurzvideos. Schau und hör dir dieses Reel komplett an.
Bewerte je 0-10: hook (erste 2 Sekunden), tempo (Schnitte, Bewegung, Dopamin), bild (eigenständiger, schöner
Look, Bilder passen zur Erzählung, keine Fehler), stimme (natürlich, emotional, nicht roboterhaft),
untertitel (lesbar, synchron), ende (will man Teil n+1 sehen?). Dazu gesamt (0-100) und die 3 wichtigsten
konkreten Verbesserungen. Antworte NUR mit JSON:
{"scores": {"hook": int, "tempo": int, "bild": int, "stimme": int, "untertitel": int, "ende": int},
 "gesamt": int, "verbesserungen": [str, str, str]}"""


def _save(name, data):
    REVIEWS.mkdir(parents=True, exist_ok=True)
    (REVIEWS / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def improve_series(series, ask, name):
    """Lässt die Serie bewerten und bei Bedarf überarbeiten. Gibt die beste Version zurück."""
    best, best_score, rounds = series, -1, []
    current = series
    for _ in range(4):
        try:
            crit = ask(JURY_PROMPT.format(series=json.dumps(current, ensure_ascii=False)))
            score = int(crit.get("gesamt", 0))
        except Exception as e:
            print("  Skript-Jury nicht erreichbar:", str(e)[:150])
            break
        rounds.append(crit)
        print(f"  Skript-Jury: {score}/100 – {crit.get('fazit', '')[:140]}")
        if score > best_score:
            best, best_score = current, score
        if score >= SERIES_MIN or len(rounds) == 4:
            break
        try:
            current = ask(REWRITE_PROMPT.format(critique=json.dumps(crit, ensure_ascii=False),
                                                series=json.dumps(current, ensure_ascii=False)))
            assert len(current.get("levels", [])) == 8
        except Exception as e:
            print("  Überarbeitung fehlgeschlagen:", str(e)[:150])
            break
    _save(f"serie_{name}", {"best_score": best_score, "rounds": rounds})
    return best


def review_video(path, name):
    """Gemini bewertet das fertige Video. Gibt (punkte, bewertung) zurück; bei Fehlern (None, {})."""
    key = os.environ.get("GEMINI_API_KEY")
    path = Path(path)
    if not key or path.stat().st_size > 19_000_000:
        return None, {}
    body = {"contents": [{"parts": [{"inlineData": {"mimeType": "video/mp4",
                                                   "data": base64.b64encode(path.read_bytes()).decode()}},
                                    {"text": VIDEO_PROMPT}]}],
            "generationConfig": {"responseMimeType": "application/json"}}
    for model in ("gemini-2.5-flash", "gemini-flash-latest"):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"] if not p.get("thought"))
            res = json.loads(re.sub(r"^```(json)?|```$", "", text.strip()).strip())
            _save(f"video_{name}", res)
            return int(res.get("gesamt", 0)), res
        except Exception as e:
            print("  Video-Jury:", model, str(e)[:150])
    return None, {}


DESIGN_PROMPT = """Ihr seid eine strenge Design-Jury für virale Reels. Vorbilder: simpsonsvorhersage.n und herr.amorim
(bunte 3D-Obst- und Gemüsemenschen mit Zahl auf der Stirn) sowie _8_levels (warme, detailreiche Webcomic-Szenen).
Bewertet jedes der {n} Bilder (Reihenfolge wie gezeigt, Index ab 0) je 0-10: exotisch_individuell,
nicht_menschlich_realistisch (10 = klar Cartoon/Figur, 0 = Foto eines Menschen oder Anime), wiedererkennung,
lesbarkeit_handy, passt_zur_szene. Szene: {scene}
Antworte NUR mit JSON: {{"punkte": [int pro Bild, 0-50], "sieger": int, "warum": str}}"""


def pick_image(paths, scene):
    """Gemini schaut sich mehrere Bildvarianten an und wählt die beste. Gibt (index, bewertung) zurück."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key or len(paths) < 2:
        return 0, {}
    parts = [{"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(Path(p).read_bytes()).decode()}}
             for p in paths]
    parts.append({"text": DESIGN_PROMPT.format(n=len(paths), scene=scene[:600])})
    body = {"contents": [{"parts": parts}], "generationConfig": {"responseMimeType": "application/json"}}
    for model in ("gemini-2.5-flash", "gemini-flash-latest"):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.load(r)
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"] if not p.get("thought"))
            res = json.loads(re.sub(r"^```(json)?|```$", "", text.strip()).strip())
            i = int(res.get("sieger", 0))
            return (i if 0 <= i < len(paths) else 0), res
        except Exception as e:
            print("  Design-Jury:", model, str(e)[:150])
    return 0, {}
