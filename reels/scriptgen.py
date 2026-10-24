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
BLUEPRINTS = ROOT / "data" / "blueprints.json"

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


# --- Version 3: Story-Serien („Der Level-Aufzug“, „Sherwood heute“) -------------------------------------------

FRAMES = {
    "aufzug": {
        "name": "Der Level-Aufzug",
        "text": """Wiedererkennung des Kanals: "Der Level-Aufzug". Jedes Video beginnt mit geschlossenen Aufzugtüren,
die Anzeige springt auf das Level, "Ding", die Türen gehen auf und wir stehen MITTEN im Leben einer Figur.
Jede Serie = ein Aufzug durch 8 Etagen eines Themas (Level 1 = unten/schlechteste Lage, Level 8 = ganz oben).
Level 8 bleibt bis zum Schluss ein Geheimnis und überrascht.""",
        "setting": "englische Beschreibung des Ortes, an dem die Figuren leben (z. B. 'a big city in Germany today')",
        "art": "",
    },
    "sherwood": {
        "name": "Sherwood heute",
        "text": """Wiedererkennung des Kanals: "Sherwood heute" – die gemeinfreie Robin-Hood-Sage in der Gegenwart.
Nottingham ist eine heutige Großstadt, Sherwood ein Stadtviertel. Die 8 Level sind 8 Ränge dieser Welt,
von unten (z. B. Bettler am Sherwood-Park) bis oben (z. B. der Sheriff von Nottingham bzw. Prinz John).
Figuren sind moderne Versionen der klassischen Sagenfiguren (Little John, Bruder Tuck, Maid Marian, Will
Scarlet, Müllerssohn Much, Guy von Gisborne, der Sheriff) mit heutigen Jobs und echten heutigen Zahlen.
Level 8 ist eine Überraschung: Robin Hood selbst und wer er heute wirklich ist.
Nutze nur die gemeinfreie Sage, nichts aus Filmen oder Serien.""",
        "setting": "englische Beschreibung: 'modern-day Nottingham with a touch of medieval Sherwood'",
        "art": "modern-day Robin Hood legend, characters mix modern clothes with subtle medieval details (green hood, bow motif), ",
    },
}

FRAMES["pixel"] = {
    "name": "Die Pixelwelt",
    "text": """Wiedererkennung des Kanals: "Die Pixelwelt" – ein eigenes Retro-Videospiel (kein bekanntes Spiel nachbauen,
keine bekannten Spielfiguren). Jede Serie ist ein Spiel mit 8 Welten. Jedes Level ist eine Welt mit einer Spielfigur
(ein heutiger Mensch als Spielheld) und einem "Gegner" aus dem echten Leben (Miete, Dispo, Chef, Inflation ...).
Level 1 = Startwelt, ganz unten. Level 8 = Endboss-Welt, bleibt bis zum Schluss geheim und überrascht.
Nutze Spiele-Sprache sparsam und clever (Leben, Punkte, Power-up, Game over, Endboss).""",
    "setting": "englische Beschreibung der Spielwelt (z. B. 'a retro side-scrolling video game world set in a German city')",
    "art": "",
    "style": ("detailed 16-bit retro pixel art video game scene, side-scrolling platformer look, vibrant colors, "
              "chunky pixel characters with expressive faces, HUD-free, no text, no letters, no watermark"),
}

NEXT_LINE = {"de": "Das siehst du in Level {n}.", "en": "You'll see that in Level {n}.",
             "es": "Lo verás en el nivel {n}.", "pt": "Você vai ver isso no nível {n}.",
             "fr": "Tu verras ça au niveau {n}."}

SERIES_PROMPT = """Du bist Head-Autor eines viralen Kurzvideo-Kanals im Format "Die 8 Level von ...".
{frame_text}
Pro Video wird EIN Level als echte, spannende Mini-Geschichte erzählt. Die Zuschauer werden ab dem ersten
Satz in die Geschichte hineingezogen und wollen unbedingt den nächsten Teil sehen.

Thema der Serie: {topic}
Sprache und Kultur: {lang_name}. Schreibe muttersprachlich und an das Land angepasst ({country}), mit
realistischen, konkreten Zahlen (Gehälter, Mieten, Preise) für dieses Land. Keine Übersetzung.

Psychologische Mechanik (in jedem Teil anwenden):
- Erster Satz = Hook in max. 12 Wörtern, der mitten in eine Szene springt, mit überraschender Zahl oder
  Widerspruch, z. B. "Level 3: 80.000 Euro im Jahr – und trotzdem pleite."
- Danach eine echte Szene mit Konflikt: Name, Alter, Job, ein konkreter Moment, ein Detail, eine Wendung.
- Selbstvergleich: Zuschauer sollen sich einordnen ("Kennst du das?", "Wo stehst du?").
- Emotion: Stolz, Neid, Scham, Hoffnung oder Überraschung – ehrlich, nicht kitschig.
- Vorletzter Satz = Teaser auf das nächste Level, ohne es zu verraten.
- LETZTER Satz ist IMMER exakt: "{next_line}" (mit der Nummer des nächsten Levels; nur bei Level 8 stattdessen
  die Frage an die Zuschauer, welches Thema als Nächstes kommen soll).

Regeln: Keine echten Personen, keine Marken-Diffamierung, keine Anlage-/Steuer-/Rechtsberatung,
keine Einkommensversprechen. Zahlen realistisch und plausibel.

Für jedes Level:
- name: Vorname + Alter + Rolle, z. B. "Lena, 27, Pflegerin"
- badge: Kernzahl, max. 18 Zeichen, z. B. "3.200 € netto"
- verdict: Urteil in 1-3 Wörtern in GROSSBUCHSTABEN, z. B. "NICHT REICH"
- story: gesprochener Text, 130-150 Wörter (ca. 55-60 Sekunden), sehr kurze Sätze, Du-Ansprache erlaubt.
- character: englische, feste Beschreibung des Aussehens der Figur (Geschlecht, Alter, Haare, Gesicht,
  Kleidung, ein markantes Detail), max. 30 Wörter. Wird in jedes Bild dieses Levels übernommen.
- visual: englischer Bildprompt für die Hauptszene (Tätigkeit, Gefühl, Umgebung, Licht). Keine Schrift im Bild.
- scenes: 4 weitere englische Bildprompts, je ein Schlüsselmoment der Geschichte in der richtigen Reihenfolge,
  ausdrucksstarke Mimik und Gestik, abwechslungsreiche Perspektiven (Nahaufnahme, Totale, Detail).
- caption: 1 Satz + Frage an die Zuschauer + 4-6 Hashtags in der Zielsprache.

Außerdem:
- title: "Die 8 Level von ..." in der Zielsprache, max. 40 Zeichen.
- house: {setting}.

Antworte NUR mit JSON:
{{"title": str, "house": str, "levels": [{{"n": 1, "name": str, "badge": str, "verdict": str, "story": str,
"character": str, "visual": str, "scenes": [str, str, str, str], "caption": str}}, ... bis n=8]}}
"""

COUNTRIES = {"de": "Deutschland", "en": "USA", "es": "Spanien", "pt": "Brasilien", "fr": "Frankreich"}

SERIES_TOPIC_PROMPT = """Schlage ein neues Thema für die Serie "Die 8 Level von ..." vor (Haus mit 8 Stockwerken,
jede Etage ein Level). Es muss sofort Selbstvergleich auslösen und breites Interesse haben:
Geld, Gehalt, Wohnen, Studium, Job, Status, Lebensstil, Gewohnheiten, KI im Alltag.
Bereits verwendet (nicht wiederholen): {used}
Antworte NUR mit JSON: {{"topic": str}} (Thema auf Deutsch, max. 6 Wörter)."""


def validate_series(s):
    assert len(s["levels"]) == 8, "es müssen 8 Level sein"
    for i, lv in enumerate(s["levels"], 1):
        lv["n"] = i
        for k in ("name", "badge", "verdict", "story", "visual", "caption"):
            assert lv.get(k), f"Level {i}: {k} fehlt"
        lv["scenes"] = (lv.get("scenes") or [])[:4]
    assert s.get("title") and s.get("house")
    return s


def ensure_next_line(s, lang):
    """Fester Schlusssatz jedes Teils (Wiedererkennung): „Das siehst du in Level X.“"""
    for lv in s["levels"][:7]:
        line = NEXT_LINE.get(lang, NEXT_LINE["en"]).format(n=lv["n"] + 1)
        story = lv["story"].strip()
        if not story.endswith(line):
            story = re.sub(r"\s*(Teil|Part|Parte|Partie)\s*\d+\.?\s*$", "", story).rstrip()
            lv["story"] = f"{story} {line}"
    return s


def next_series_topic(used):
    queue = json.loads((ROOT / "data" / "series_topics.json").read_text(encoding="utf-8"))
    for t in queue:
        if t not in used:
            return t
    return ask(SERIES_TOPIC_PROMPT.format(used=", ".join(used[-60:]) or "keine"))["topic"]


def blueprint_hint(topic):
    """Bauplan eines erfolgreichen englischen Videos (tools/trend_scout.py), falls das Thema daher stammt."""
    bp = json.loads(BLUEPRINTS.read_text(encoding="utf-8")).get(topic) if BLUEPRINTS.exists() else None
    if not bp:
        return ""
    rules = "\n".join(f"- {r}" for r in bp["regeln"])
    hooks = " | ".join(bp["hook_ideen"])
    views = f" mit {bp['aufrufe']:,} Aufrufen".replace(",", ".") if bp.get("aufrufe") else ""
    return (f"\nDieses Thema basiert auf der Mechanik eines erfolgreichen englischen Videos{views}."
            " Übernimm nur die Mechanik, keinen Inhalt:\n"
            f"- Hook-Typ: {bp['hook_typ']}\n- Aufbau: {bp['aufbau']}\n- Spannung: {bp['spannung']}\n"
            f"- Emotion: {bp['emotion']}\n{rules}\n- Mögliche Hooks (frei abwandeln): {hooks}\n")


def write_series(topic, lang, frame="aufzug"):
    fr = FRAMES[frame]
    prompt = SERIES_PROMPT.format(topic=topic, lang_name=LANG_NAMES[lang], country=COUNTRIES[lang],
                                  frame_text=fr["text"], setting=fr["setting"],
                                  next_line=NEXT_LINE.get(lang, NEXT_LINE["en"]).format(n="X"))
    prompt += blueprint_hint(topic)
    s = ensure_next_line(validate_series(ask(prompt)), lang)
    s.update({"lang": lang, "topic": topic, "frame": frame})
    return s
