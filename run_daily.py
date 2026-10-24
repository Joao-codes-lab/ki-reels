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

from reels import buffer, critic, imagegen, scriptgen
from reels.render import render
from reels.render_v4 import render_part as render_lift

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


def generate_series(langs, tts_backend, frames):
    """Version 3: pro Sprache und Rahmen täglich ein Teil der aktuellen Serie."""
    today = dt.date.today().isoformat()
    state = load(STATE, {})
    pending = load(PENDING, [])
    SITE.mkdir(parents=True, exist_ok=True)
    (ROOT / "out").mkdir(exist_ok=True)
    for frame in frames:
        for lang in langs:
          for part in range(int(os.environ.get("PARTS", "1"))):
              key = f"{lang}:{frame}"
              st = state.get(key)
              if part == 0 and st and st.get("last_date") == today:
                  print(f"[{key}] heute schon erledigt")
                  break
              if not st or st["next"] > 8:
                  used = [x["topic"] for x in state.get("_done", []) if x["lang"] == lang and x.get("frame") == frame]
                  topic = scriptgen.next_series_topic(used)
                  series = scriptgen.write_series(topic, lang, frame)
                  sid = f"{lang}_{frame}_{slugify(topic)}"
                  (DATA / "series").mkdir(exist_ok=True)
                  save(DATA / "series" / f"{sid}.json", series)
                  st = {"id": sid, "topic": topic, "frame": frame, "next": 1}
                  state.setdefault("_done", []).append({"lang": lang, "frame": frame, "topic": topic, "start": today})
                  print(f"[{key}] Neue Serie: {series['title']}")
              series = load(DATA / "series" / f"{st['id']}.json", None)
              n = st["next"]
              lv = series["levels"][n - 1]
              art = scriptgen.FRAMES.get(frame, {}).get("art", "")
              who = f"Main character: {lv['character']}. " if lv.get("character") else ""
              adir = ASSETS / st["id"]
              pics = []
              for i, prompt in enumerate([lv["visual"]] + lv.get("scenes", [])):
                  p = adir / f"l{n}_{i}.jpg"
                  full = f"{art}{who}{prompt}. Setting: {series['house']}"
                  style = scriptgen.FRAMES.get(frame, {}).get("style")
                  print(f"  Bild {i + 1}: {imagegen.generate(full, p, seed=n * 7919 + i, style=style)}")
                  pics.append(str(p))
              name = f"{today}_{st['id']}_teil{n}.mp4"
              info = render_lift(series, n, pics, ROOT / "out" / name, backend=tts_backend)
              shutil.copy(info["path"], SITE / name)
              score, review = critic.review_video(info["path"], name[:-4])
              print(f"  Video-Jury: {score}/100 {review.get('verbesserungen', '')}")
              caption = f"{series['title']} – Level {n}/8\n\n{lv['caption']}\n\n{DISCLOSURE[lang]}"
              if score is not None and score < critic.VIDEO_MIN:
                  print(f"  zurückgehalten (unter {critic.VIDEO_MIN} Punkten), wird nicht gepostet")
              else:
                  pending.append({"lang": lang, "frame": frame, "file": name, "caption": caption,
                                  "topic": st["topic"], "score": score})
              print(f"[{key}] {series['title']} Teil {n} -> {name} ({info['duration']} s)")
              st["next"] = n + 1
              st["last_date"] = today
              state[key] = st
              save(STATE, state)
              save(PENDING, pending)


# Design-Battle: (Bildmodell, Stil-Zusatz). Die Design-Jury wählt pro Pilot den Look für alle Szenen.
DESIGN_VARIANTS = [
    ("flux", ""),
    ("zimage", ""),
    ("flux", "glossy candy-colored textures, exaggerated cartoon proportions, dramatic reality-TV studio lighting"),
]


def image_prompt(frame, lv, scene):
    """Kurzer Bildprompt: Figur zuerst, dann Szene. Der Stil wird in imagegen VOR den Prompt gesetzt."""
    words = scene.split()
    scene = " ".join(words[:45])
    char = lv.get("character", "")
    if frame == "frucht":
        return (f"Main character: {char}. It is a cartoon fruit or vegetable creature, NOT a human. Scene: {scene}. "
                f"A small glowing digital number '{lv['badge']}' on its forehead. Every character in the image is a "
                f"fruit or vegetable creature, no human faces.")
    if frame == "fruchtmensch":
        return (f"Every character has a big fruit or vegetable INSTEAD of a human head (no human faces, no hair), on a "
                f"human body in stylish clothes. Main character: {char}. Scene: {scene}. "
                f"A small glowing digital number '{lv['badge']}' on the fruit forehead.")
    return f"Main character: {char}. Scene: {scene}"


def level_images(series, n, frame, folder, seed):
    """Titelbild in mehreren Design-Varianten, Jury wählt, dann die restlichen Szenen im Siegerlook."""
    lv = series["levels"][n - 1]
    fr = scriptgen.FRAMES.get(frame, {})
    base = fr.get("style") or imagegen.STYLE
    prompts = [image_prompt(frame, lv, p) for p in [lv["visual"]] + lv.get("scenes", [])]
    cands = []
    for j, (model, extra) in enumerate(DESIGN_VARIANTS):
        p = folder / f"l{n}_0_v{j}.jpg"
        src = imagegen.generate(prompts[0], p, seed=seed + j * 13, style=f"{base}, {extra}" if extra else base, model=model)
        if src != "placeholder":
            cands.append((p, j))
    if not cands:
        cands = [(folder / f"l{n}_0_v0.jpg", 0)]
    win, verdict = critic.pick_image([str(c[0]) for c in cands], prompts[0])
    path, j = cands[win]
    model, extra = DESIGN_VARIANTS[j]
    print(f"  Design-Battle: Variante {j} ({model}) gewinnt {verdict.get('punkte', '')} {str(verdict.get('warum', ''))[:200]}")
    look = f"{base}, {extra}" if extra else base
    pics = [str(path)]
    for i, prompt in enumerate(prompts[1:], 1):
        p = folder / f"l{n}_{i}.jpg"
        print(f"  Bild {i + 1}: {imagegen.generate(prompt, p, seed=seed + j * 13 + i, style=look, model=model)}")
        pics.append(str(p))
    qb = lv.get("quote_by") if isinstance(lv.get("quote_by"), dict) else {}
    if qb.get("character"):
        other = {"character": qb["character"], "badge": qb.get("badge", "")}
        p = folder / f"l{n}_zitat.jpg"
        src = imagegen.generate(image_prompt(frame, other, qb.get("scene") or lv["visual"]), p, seed=seed + 77,
                                style=look, model=model)
        print(f"  Zitat-Bild ({qb.get('name')}, {qb.get('badge')}): {src}")
        if src != "placeholder":
            lv["quote_image"] = str(p)
    return pics, verdict


def generate_pilots(lang, tts_backend, k=5):
    """5 Pilotfolgen (Teil 1 von 5 verschiedenen Serien) zur Auswahl durch João. Werden nicht automatisch gepostet."""
    today = dt.date.today().isoformat()
    SITE.mkdir(parents=True, exist_ok=True)
    (ROOT / "out").mkdir(exist_ok=True)
    pdir = DATA / "pilots"
    pdir.mkdir(exist_ok=True)
    used = [p["topic"] for f in pdir.glob("*.json") for p in load(f, [])]
    ideas = scriptgen.pilot_ideas(lang, used, k, rounds=int(os.environ.get("BATTLE_ROUNDS", "3")))
    if os.environ.get("ELEVENLABS_API_KEY"):
        tts_backend = "eleven"
    results = []
    for idx, idea in enumerate(ideas, 1):
        topic, frame = idea["topic"], idea["frame"]
        print(f"[Pilot {idx}] {topic} ({frame})")
        try:
            series = scriptgen.write_series(topic, lang, frame)
            sid = f"{lang}_{frame}_{slugify(topic)}"
            (DATA / "series").mkdir(exist_ok=True)
            save(DATA / "series" / f"{sid}.json", series)
            pics, verdict = level_images(series, 1, frame, ASSETS / sid, seed=7919 + idx * 101)
            name = f"{today}_pilot{idx}_{sid}_teil1.mp4"
            info = render_lift(series, 1, pics, ROOT / "out" / name, backend=tts_backend)
            shutil.copy(info["path"], SITE / name)
            score, review = critic.review_video(info["path"], name[:-4])
            print(f"  Video-Jury: {score}/100 {review.get('verbesserungen', '')}")
            results.append({"nr": idx, "topic": topic, "frame": frame, "title": series["title"], "file": name,
                            "hook": idea.get("hook"), "warum": idea.get("warum_viral"), "score": score,
                            "jury": review.get("verbesserungen"), "sid": sid,
                            "design": verdict})
        except Exception as e:
            print(f"  Pilot {idx} fehlgeschlagen: {e}")
        save(pdir / f"{today}_{lang}.json", results)


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
    ap.add_argument("--tts", default=os.environ.get("TTS", "gemini"))
    ap.add_argument("--count", type=int, default=int(os.environ.get("VIDEOS_PER_RUN", "1")))
    ap.add_argument("--base-url", default=os.environ.get("PAGES_URL", ""))
    ap.add_argument("--mode", default=os.environ.get("MODE", "series"), choices=["series", "classic", "pilots"])
    a = ap.parse_args()
    if a.step == "generate" and a.mode == "pilots":
        for lang in a.langs.split(","):
            generate_pilots(lang, a.tts, int(os.environ.get("PILOTS", "5")))
    elif a.step == "generate" and a.mode == "series":
        generate_series(a.langs.split(","), a.tts, os.environ.get("FRAMES", "aufzug").split(","))
    elif a.step == "generate":
        generate(a.langs.split(","), a.tts, a.count)
    else:
        post(a.base_url)
