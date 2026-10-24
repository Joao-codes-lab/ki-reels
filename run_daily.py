"""Tageslauf der Pipeline.

  python run_daily.py generate   # Thema wählen, Skripte schreiben, Videos rendern -> site/videos, data/pending.json
  python run_daily.py post       # Videos aus data/pending.json bei Buffer einplanen (TikTok + Instagram)

Zwischen beiden Schritten veröffentlicht der GitHub-Workflow den Ordner site/ auf GitHub Pages,
damit Buffer die Videos über eine öffentliche URL abholen kann.
"""
import argparse
import datetime as dt
import json
import os
import shutil
from pathlib import Path

from reels import buffer, imagegen, scriptgen
from reels.render import render
from reels.render_story import render_part

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SITE = ROOT / "site" / "videos"
PENDING = DATA / "pending.json"
STATE = DATA / "series_state.json"
ASSETS = ROOT / "assets"

DISCLOSURE = {
    "de": "🤖 KI-generiert (Skript, Stimme, Grafik)",
    "en": "🤖 AI-generated (script, voice, graphics)",
    "es": "🤖 Generado con IA",
    "pt": "🤖 Gerado por IA",
    "fr": "🤖 Généré par IA",
}


def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def generate(langs, tts_backend, count):
    today = dt.date.today().isoformat()
    history = load(scriptgen.HISTORY, [])
    pending = load(PENDING, [])
    SITE.mkdir(parents=True, exist_ok=True)
    for _ in range(count):
        topic = scriptgen.next_topic()
        for lang in langs:
            spath = scriptgen.write_script(topic, lang, ROOT / "content" / today)
            script = json.loads(spath.read_text(encoding="utf-8"))
            name = f"{today}_{script['id']}.mp4"
            info = render(spath, ROOT / "out" / name, backend=tts_backend)
            shutil.copy(info["path"], SITE / name)
            caption = f"{script['caption']}\n\n{DISCLOSURE[lang]}"
            pending.append({"lang": lang, "file": name, "caption": caption, "topic": topic})
            print(f"[{lang}] {script['title']} -> {name} ({info['duration']} s)")
        history.append({"date": today, "topic": topic, "langs": langs})
        save(scriptgen.HISTORY, history)
    save(PENDING, pending)


def slugify(text):
    import re
    return re.sub(r"[^a-z0-9]+", "_", text.lower())[:40].strip("_")


def generate_series(langs, tts_backend):
    """Version 2: pro Sprache täglich ein Teil der aktuellen Serie „Das Haus der 8 Level“."""
    today = dt.date.today().isoformat()
    state = load(STATE, {})
    pending = load(PENDING, [])
    SITE.mkdir(parents=True, exist_ok=True)
    for lang in langs:
        st = state.get(lang)
        if st and st.get("last_date") == today:
            print(f"[{lang}] heute schon erledigt")
            continue
        if not st or st["next"] > 8:
            used = [x["topic"] for x in state.get("_done", []) if x["lang"] == lang]
            topic = scriptgen.next_series_topic(used)
            series = scriptgen.write_series(topic, lang)
            sid = f"{lang}_{slugify(topic)}"
            (DATA / "series").mkdir(exist_ok=True)
            save(DATA / "series" / f"{sid}.json", series)
            st = {"id": sid, "topic": topic, "next": 1}
            state.setdefault("_done", []).append({"lang": lang, "topic": topic, "start": today})
            print(f"[{lang}] Neue Serie: {series['title']}")
        series = load(DATA / "series" / f"{st['id']}.json", None)
        adir = ASSETS / st["id"]
        floors = []
        for lv in series["levels"]:  # Hauptbild jeder Etage (einmal pro Serie)
            p = adir / f"floor_{lv['n']}.jpg"
            who = f"Main character: {lv['character']}. " if lv.get("character") else ""
            src = imagegen.generate(f"Inside {series['house']}, floor {lv['n']} of 8. {who}{lv['visual']}", p, seed=lv["n"] * 7919)
            if src not in ("cache",):
                print(f"  Bild Etage {lv['n']}: {src}")
            floors.append(str(p))
        n = st["next"]
        lv = series["levels"][n - 1]
        scenes = [floors[n - 1]]
        for i, prompt in enumerate(lv.get("scenes", [])):
            p = adir / f"l{n}_s{i + 1}.jpg"
            who = f"Main character: {lv['character']}. " if lv.get("character") else ""
            print(f"  Szene {i + 1}: {imagegen.generate(who + prompt, p, seed=n * 7919)}")  # gleicher Seed = ähnlichere Figur
            scenes.append(str(p))
        name = f"{today}_{st['id']}_teil{n}.mp4"
        (ROOT / "out").mkdir(exist_ok=True)
        info = render_part(series, n, {"floors": floors, "scenes": scenes}, ROOT / "out" / name, backend=tts_backend)
        shutil.copy(info["path"], SITE / name)
        caption = f"{series['title']} – Level {n}/8\n\n{lv['caption']}\n\n{DISCLOSURE[lang]}"
        pending.append({"lang": lang, "file": name, "caption": caption, "topic": st["topic"]})
        print(f"[{lang}] {series['title']} Teil {n} -> {name} ({info['duration']} s)")
        st["next"] = n + 1
        st["last_date"] = today
        state[lang] = st
        save(STATE, state)
    save(PENDING, pending)


def post(base_url):
    pending = load(PENDING, [])
    remaining = []
    cache = {}
    for item in pending:
        key = os.environ.get(f"BUFFER_KEY_{item['lang'].upper()}")
        if not key:
            print(f"[{item['lang']}] kein BUFFER_KEY_{item['lang'].upper()} gesetzt, Video bleibt in der Warteschlange")
            remaining.append(item)
            continue
        if key not in cache:
            cache[key] = [c for c in buffer.channels(key) if c["service"] in ("tiktok", "instagram")]
        url = f"{base_url.rstrip('/')}/videos/{item['file']}"
        failed = False
        for ch in cache[key]:
            if ch["id"] in item.get("done", []):
                continue
            try:
                pid = buffer.queue_video(key, ch["id"], item["caption"], url)
                item.setdefault("done", []).append(ch["id"])
                print(f"[{item['lang']}] {ch['service']} ({ch['name']}): eingeplant, Post {pid}")
            except Exception as e:
                failed = True
                print(f"[{item['lang']}] {ch['service']} ({ch['name']}): FEHLER {e}")
        if failed or not cache[key]:
            remaining.append(item)
    save(PENDING, remaining)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["generate", "post"])
    ap.add_argument("--langs", default=os.environ.get("LANGS", "de,en"))
    ap.add_argument("--tts", default=os.environ.get("TTS", "edge"))
    ap.add_argument("--count", type=int, default=int(os.environ.get("VIDEOS_PER_RUN", "1")))
    ap.add_argument("--base-url", default=os.environ.get("PAGES_URL", ""))
    ap.add_argument("--mode", default=os.environ.get("MODE", "series"), choices=["series", "classic"])
    a = ap.parse_args()
    if a.step == "generate" and a.mode == "series":
        generate_series(a.langs.split(","), a.tts)
    elif a.step == "generate":
        generate(a.langs.split(","), a.tts, a.count)
    else:
        post(a.base_url)
