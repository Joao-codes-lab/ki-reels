"""Schreibt neue Level-Skripte mit einer kostenlosen KI (Gemini, Ausweich: Groq).

Schlüssel kommen aus Umgebungsvariablen: GEMINI_API_KEY und/oder GROQ_API_KEY.
"""
import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "data" / "history.json"
TOPICS = ROOT / "data" / "topics.json"

LANG_NAMES = {"de": "Deutsch", "en": "English", "es": "Español", "pt": "Português (Brasil)", "fr": "Français"}

PROMPT = """Du schreibst Skripte für ein virales Kurzvideo-Format auf TikTok und Instagram Reels.
Format: "Die 8 Level von ..." – eine Treppe von Anfänger (Level 1) bis Profi (Level 8) zu einem Thema
aus der Nische KI-Tools, Produktivität und Geld verdienen mit KI.

Thema: {topic}
Sprache des Skripts: {lang_name}. Schreibe muttersprachlich und an die Kultur angepasst, nicht übersetzt.

Regeln:
- Hook (max. 20 Wörter): provoziert Selbstvergleich, z. B. "Die meisten bleiben bei Level 2 hängen. Wo bist du?"
- 8 Level, jedes mit kurzem, einprägsamem Namen (2-3 Wörter, z. B. "Der Kopierer") und Text (14-22 Wörter).
- Jedes Level enthält einen konkreten, sofort nutzbaren Tipp. Steigerung muss logisch sein.
- Nur korrekte, überprüfbare Aussagen. Keine Einkommensversprechen, keine Finanz-, Rechts- oder Gesundheitsberatung.
- CTA (max. 22 Wörter): "Folge für Teil 2" plus Hinweis auf kostenlose/günstige Vorlagen im Link in der Bio.
- caption: 1 Frage an die Zuschauer + 4-6 passende Hashtags in der Zielsprache. Keine Emojis außer max. 1.
- keywords: 3 Suchbegriffe, nach denen Leute in der Zielsprache suchen würden.
- title: "Die 8 Level ..." in der Zielsprache, max. 45 Zeichen.

Antworte NUR mit JSON in genau diesem Schema:
{{"title": str, "hook": str, "levels": [{{"n": 1, "name": str, "text": str}}, ... bis n=8],
  "cta": str, "caption": str, "keywords": [str, str, str]}}
"""

TOPIC_PROMPT = """Schlage ein neues Thema für ein Kurzvideo "Die 8 Level von ..." vor.
Nische: KI-Tools, Produktivität, Lernen, Geld verdienen mit KI, Nebenjob/Student-Hacks mit KI.
Es soll breites Interesse wecken und Neugier auslösen. Bereits verwendet (nicht wiederholen): {used}
Antworte NUR mit JSON: {{"topic": str}} (Thema auf Deutsch, max. 8 Wörter)."""


GEMINI_MODELS = [m for m in (os.environ.get("GEMINI_MODEL"), "gemini-flash-latest", "gemini-flash-lite-latest",
                              "gemini-2.5-flash") if m]


def _gemini(prompt):
    key = os.environ["GEMINI_API_KEY"]
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9}}
    errors = []
    for model in dict.fromkeys(GEMINI_MODELS):  # Reihenfolge behalten, Duplikate raus
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts if not p.get("thought"))
        except Exception as e:
            errors.append(f"{model}: {e}")
    raise RuntimeError("; ".join(errors))


def _groq(prompt):
    key = os.environ["GROQ_API_KEY"]
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}, "temperature": 0.9}
    req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"]


def ask(prompt):
    errors = []
    for name, fn, env in (("gemini", _gemini, "GEMINI_API_KEY"), ("groq", _groq, "GROQ_API_KEY")):
        if not os.environ.get(env):
            continue
        try:
            text = fn(prompt)
            return json.loads(re.sub(r"^```(json)?|```$", "", text.strip()).strip())
        except Exception as e:  # nächste KI versuchen
            errors.append(f"{name}: {e}")
    raise RuntimeError("Keine KI erreichbar: " + "; ".join(errors or ["kein API-Schlüssel gesetzt"]))


def validate(s):
    assert len(s["levels"]) == 8, "es müssen 8 Level sein"
    for i, lv in enumerate(s["levels"], 1):
        lv["n"] = i
        assert lv["name"] and lv["text"]
    for k in ("title", "hook", "cta", "caption"):
        assert s.get(k), f"{k} fehlt"
    return s


def load_history():
    return json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []


def next_topic():
    used = [h["topic"] for h in load_history()]
    queue = json.loads(TOPICS.read_text(encoding="utf-8")) if TOPICS.exists() else []
    for t in queue:
        if t not in used:
            return t
    return ask(TOPIC_PROMPT.format(used=", ".join(used[-60:]) or "keine"))["topic"]


def write_script(topic, lang, out_dir):
    s = validate(ask(PROMPT.format(topic=topic, lang_name=LANG_NAMES[lang])))
    slug = re.sub(r"[^a-z0-9]+", "_", topic.lower())[:40].strip("_")
    s.update({"lang": lang, "topic": topic, "id": f"{lang}_{slug}"})
    path = Path(out_dir) / f"{s['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
