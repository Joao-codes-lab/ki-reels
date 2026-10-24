"""Findet gut laufende englische Kurzvideos und baut daraus deutsche Serien-Ideen.

  python tools/trend_scout.py --per-query 15 --top 5 [--research research]

1. Sucht YouTube Shorts zu den Suchbegriffen aus data/trend_queries.json (yt-dlp, kein Login nötig)
   und nimmt die meistgesehenen englischen Videos. Zusätzlich werden Transkripte aus
   tools/analyze_reels.py (Ordner --research, z. B. Instagram/TikTok-Links) mit einbezogen.
2. Gemini filtert themenfremde Treffer aus und schaut sich die passenden Videos direkt über ihre
   YouTube-URL an (Ton + Bild). Nur falls das scheitert: Tonspur laden und mit faster-whisper transkribieren.
3. Gemini zerlegt jedes Video in seinen Bauplan (Hook, Aufbau, Spannungsbogen, Emotion) und
   entwirft daraus ein eigenes deutsches Thema für „Das Haus der 8 Level“. Übernommen wird nur
   die Mechanik, nie Text, Figuren oder Bilder des Originals.
4. Ergebnis: data/adaptations/<datum>.md (Bericht), data/blueprints.json (Bauplan je Thema),
   neue Themen vorne in data/series_topics.json. scriptgen.write_series nutzt den Bauplan.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from reels import scriptgen  # noqa: E402

DATA = ROOT / "data"
QUERIES = DATA / "trend_queries.json"
SEEN = DATA / "trend_seen.json"
BLUEPRINTS = DATA / "blueprints.json"
SERIES_TOPICS = DATA / "series_topics.json"

ADAPT_PROMPT = """Du analysierst ein erfolgreiches englisches Kurzvideo und adaptierst sein Erfolgsrezept
für einen deutschen Kanal. Der Kanal heißt "Das Haus der 8 Level": Jede Serie ist ein Haus mit 8 Stockwerken,
auf jeder Etage lebt eine Figur, die ein Level eines Themas zeigt (Level 1 unten, Level 8 Penthouse).
Pro Video ein Stockwerk, offene Schleife am Ende jedes Teils. Themen: Geld, Gehalt, Wohnen, Studium, Job,
Status, Lebensstil, Gewohnheiten, KI im Alltag.

Originalvideo: "{title}" von {channel}, {views} Aufrufe, {duration} s.
Beschreibung: {description}
{material}

Aufgabe:
1. Zerlege, WARUM das Video funktioniert (Mechanik, nicht Inhalt).
2. Entwirf daraus ein eigenes deutsches Serienthema, das dieselbe Mechanik nutzt, aber auf Deutschland
   zugeschnitten ist (deutsche Zahlen, Preise, Alltag). Es muss eine eigenständige Idee sein: keine Sätze,
   Namen, Figuren, Witze oder Bildideen des Originals übernehmen, nichts übersetzen.
3. Bewerte ehrlich, wie gut es zu unserem Format passt (fit 1-10). Passt es nicht, fit niedrig setzen.

Antworte NUR mit JSON:
{{"hook_typ": str, "hook_original_kurz": str (max. 12 Wörter, sinngemäß auf Deutsch),
  "aufbau": str (Ablauf in Sekunden/Beats), "spannung": str (wie Zuschauer gehalten werden),
  "emotion": str, "design": str (Bildstil, Schrift, Schnitttempo, Musik; max. 30 Wörter),
  "warum_es_funktioniert": str (max. 40 Wörter),
  "de_thema": str (max. 6 Wörter, passt in "Die 8 Level von ..."),
  "de_hook_ideen": [str, str, str] (eigene deutsche Hooks, max. 12 Wörter),
  "regeln_fuer_autor": [str, str, str] (konkrete Anweisungen, wie die Mechanik in unsere Serie kommt),
  "fit": int}}
"""


FILTER_PROMPT = """Welche dieser YouTube Shorts passen thematisch zu einem Kanal über Geld, Gehalt, Reichtum,
Wohnen, Job, Status, Lebensstil, Gewohnheiten oder KI im Alltag, sind englischsprachig und leben von
gesprochener Erklärung oder Story (keine Musikvideos, Filmausschnitte, Comedy-Clips, Sport)?
{items}
Antworte NUR mit JSON: {{"ids": [str, ...]}} (passende IDs, beste zuerst)."""

VIDEO_HINT = "Das Video ist angehängt: werte gesprochenen Text, Bilder, Schrift, Schnitt und Musik selbst aus."


def run(cmd, timeout=600):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fmt(n):
    return f"{n:,}".replace(",", ".") if n else "?"


def search_shorts(query, n):
    """Liefert Metadaten der Treffer (ohne Download)."""
    try:
        r = run(["yt-dlp", "--no-warnings", "--ignore-errors", "--flat-playlist", "-J",
                 f"ytsearch{n}:{query} #shorts"], timeout=180)
        entries = json.loads(r.stdout).get("entries") or []
    except Exception as e:  # Suche darf den Lauf nicht abbrechen
        print(f"Suche fehlgeschlagen ({query}): {e}")
        return []
    out = []
    for e in entries:
        dur = e.get("duration") or 0
        if not e.get("id") or (dur and dur > 180):
            continue
        out.append({"id": e["id"], "url": f"https://www.youtube.com/shorts/{e['id']}",
                    "title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader") or "",
                    "views": e.get("view_count") or 0, "duration": dur, "query": query})
    return out


def transcribe_url(model, url):
    with tempfile.TemporaryDirectory() as tmp:
        r = run(["yt-dlp", "--no-warnings", "-f", "bestaudio/best", "-o", f"{tmp}/a.%(ext)s",
                 "--write-info-json", url])
        files = [p for p in Path(tmp).glob("a.*") if p.suffix != ".json"]
        if not files:
            print(f"Download fehlgeschlagen ({url}): {r.stderr[-300:]}")
            return None, {}
        info = load(Path(tmp) / "a.info.json", {})
        segs, meta = model.transcribe(str(files[0]), vad_filter=True)
        text = " ".join(s.text.strip() for s in segs)
        info["_lang"] = meta.language
        return text, info


def gemini_video(url, prompt):
    """Gemini schaut sich das öffentliche YouTube-Video direkt an (kein Download nötig)."""
    key = os.environ["GEMINI_API_KEY"]
    body = {"contents": [{"parts": [{"file_data": {"file_uri": url}}, {"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7}}
    errors = []
    for model in dict.fromkeys(scriptgen.GEMINI_MODELS):
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                parts = json.load(r)["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            return json.loads(re.sub(r"^```(json)?|```$", "", text.strip()).strip())
        except Exception as e:
            errors.append(f"{model}: {e}")
    raise RuntimeError("; ".join(errors))


def filter_relevant(cands):
    if not cands:
        return []
    listing = "\n".join(f"- {c['id']}: {c['title']} ({c['channel']})" for c in cands)
    try:
        ids = scriptgen.ask(FILTER_PROMPT.format(items=listing)).get("ids") or []
    except Exception as e:  # ohne Filter weiter, die Passung (fit) sortiert später aus
        print(f"Themenfilter fehlgeschlagen: {e}")
        return cands
    by_id = {c["id"]: c for c in cands}
    return [by_id[i] for i in ids if i in by_id]


def research_items(folder):
    """Transkripte aus tools/analyze_reels.py (Instagram/TikTok-Links von João)."""
    items = []
    for md in sorted(Path(folder).glob("*/*.md")):
        text = md.read_text(encoding="utf-8")
        if "## Transkript" not in text or "Sprache: en" not in text:
            continue
        url = next((ln[7:].strip() for ln in text.splitlines() if ln.startswith("- URL: ")), md.stem)
        items.append({"id": f"{md.parent.name}_{md.stem}", "url": url, "title": md.stem,
                      "channel": md.parent.name, "views": 0, "duration": 0, "query": "research",
                      "transcript": text.split("## Transkript", 1)[1].strip(),
                      "description": text.split("## Beschreibung", 1)[-1].split("## Transkript")[0].strip()})
    return items


def adapt(item):
    fields = dict(title=item["title"], channel=item["channel"], views=fmt(item["views"]),
                  duration=item["duration"] or "?", description=(item.get("description") or "")[:600])
    if item.get("transcript"):
        a = scriptgen.ask(ADAPT_PROMPT.format(material="Transkript:\n" + item["transcript"][:4000], **fields))
    else:
        a = gemini_video(item["url"], ADAPT_PROMPT.format(material=VIDEO_HINT, **fields))
    a["fit"] = int(a.get("fit") or 0)
    assert a.get("de_thema") and a.get("regeln_fuer_autor")
    return a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-query", type=int, default=15, help="Suchtreffer pro Suchbegriff")
    ap.add_argument("--top", type=int, default=5, help="so viele Videos analysieren")
    ap.add_argument("--min-views", type=int, default=300_000)
    ap.add_argument("--min-fit", type=int, default=7, help="ab dieser Passung kommt das Thema in die Warteschlange")
    ap.add_argument("--research", default="", help="Ordner mit Ergebnissen von analyze_reels.py")
    a = ap.parse_args()

    seen = set(load(SEEN, []))
    candidates = {}
    for q in load(QUERIES, []):
        for c in search_shorts(q, a.per_query):
            if c["id"] not in seen and c["views"] >= a.min_views:
                candidates.setdefault(c["id"], c)
    top_views = sorted(candidates.values(), key=lambda c: -c["views"])[:a.top * 4]
    relevant = filter_relevant(top_views)
    seen.update(c["id"] for c in top_views if c not in relevant)  # themenfremd, nicht erneut prüfen
    picked = relevant[:a.top]
    extra = [i for i in research_items(a.research) if i["id"] not in seen] if a.research else []
    print(f"{len(candidates)} Kandidaten, {len(relevant)} passend, analysiere {len(picked)} + {len(extra)} aus Research")

    model = None
    results = []
    for item in picked + extra:
        try:
            item["adaption"] = adapt(item)
        except Exception as e:
            print(f"Video-Analyse fehlgeschlagen ({item['title']}): {e}")
            if item.get("transcript"):
                continue
            if model is None:  # Ausweg: Ton laden und selbst transkribieren
                from faster_whisper import WhisperModel
                model = WhisperModel("small", device="cpu", compute_type="int8")
            text, info = transcribe_url(model, item["url"])
            if not text or info.get("_lang") != "en" or len(text.split()) < 25:
                print(f"übersprungen (kein englischer Sprechtext oder Download gesperrt): {item['title']}")
                continue
            item["transcript"] = text
            item["description"] = info.get("description") or ""
            try:
                item["adaption"] = adapt(item)
            except Exception as e:
                print(f"Adaption fehlgeschlagen ({item['title']}): {e}")
                continue
        seen.add(item["id"])
        results.append(item)
        ad = item["adaption"]
        print(f"[fit {ad['fit']}] {item['title']} ({item['views']:,} Aufrufe) -> {ad['de_thema']}")

    blueprints = load(BLUEPRINTS, {})
    queue = load(SERIES_TOPICS, [])
    new_topics = []
    for item in sorted(results, key=lambda i: -i["adaption"]["fit"]):
        ad = item["adaption"]
        if ad["fit"] < a.min_fit or ad["de_thema"] in queue or ad["de_thema"] in blueprints:
            continue
        blueprints[ad["de_thema"]] = {"quelle": item["url"], "aufrufe": item["views"],
                                      "hook_typ": ad["hook_typ"], "aufbau": ad["aufbau"],
                                      "spannung": ad["spannung"], "emotion": ad["emotion"],
                                      "design": ad.get("design", ""),
                                      "hook_ideen": ad["de_hook_ideen"], "regeln": ad["regeln_fuer_autor"]}
        new_topics.append(ad["de_thema"])
    save(SERIES_TOPICS, new_topics + queue)
    save(BLUEPRINTS, blueprints)
    save(SEEN, sorted(seen))

    today = dt.date.today().isoformat()
    lines = [f"# Trend-Scout {today}", "",
             f"Neue Themen in der Warteschlange: {', '.join(new_topics) or 'keine'}", ""]
    for item in results:
        ad = item["adaption"]
        lines += [f"## {item['title']}", "",
                  f"- Quelle: {item['url']} ({item['channel']}, {fmt(item['views'])} Aufrufe)",
                  f"- Hook: {ad['hook_typ']} – „{ad.get('hook_original_kurz', '')}“",
                  f"- Aufbau: {ad['aufbau']}", f"- Spannung: {ad['spannung']}", f"- Emotion: {ad['emotion']}",
                  f"- Design: {ad.get('design', '')}",
                  f"- Warum es funktioniert: {ad['warum_es_funktioniert']}",
                  f"- **Deutsche Adaption ({ad['fit']}/10): {ad['de_thema']}**",
                  *[f"  - Hook-Idee: {h}" for h in ad["de_hook_ideen"]], ""]
    save_md = DATA / "adaptations" / f"{today}.md"
    save_md.parent.mkdir(parents=True, exist_ok=True)
    save_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"Bericht: {save_md.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
