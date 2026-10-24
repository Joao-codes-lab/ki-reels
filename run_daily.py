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

from reels import buffer, scriptgen
from reels.render import render

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SITE = ROOT / "site" / "videos"
PENDING = DATA / "pending.json"

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
    a = ap.parse_args()
    if a.step == "generate":
        generate(a.langs.split(","), a.tts, a.count)
    else:
        post(a.base_url)
