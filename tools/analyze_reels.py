"""Analysiert öffentliche Reels: Standbilder (Design) + Transkript (Inhalt).

  python tools/analyze_reels.py URL [URL ...] --max 5 --out research

Nutzt yt-dlp (Download) und faster-whisper (Spracherkennung, läuft auf CPU).
Pro Reel entsteht <out>/<account>/<id>.md mit Transkript, Beschreibung, Kennzahlen und
<id>.jpg mit 6 Standbildern. Die Videos selbst werden nicht gespeichert.
"""
import argparse
import json
import os
import re
import subprocess
import urllib.request
import tempfile
from pathlib import Path

from PIL import Image


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def download(url, tmp, max_items):
    r = run(["yt-dlp", "--no-warnings", "--ignore-errors", "--playlist-end", str(max_items),
             "-f", "mp4/best", "-o", f"{tmp}/%(uploader_id)s__%(id)s.%(ext)s", "--write-info-json", url])
    print(r.stdout[-1500:], r.stderr[-1500:])
    return sorted(Path(tmp).glob("*.mp4"))


def apify_download(url, tmp, max_items):
    """Instagram mit Login-Sperre: über den Apify-Dienst „Instagram Reel Scraper“ (APIFY_TOKEN).
    Liefert die Original-Videodateien plus Beschreibung, Likes und Aufrufe."""
    token = os.environ.get("APIFY_TOKEN")
    m = re.search(r"instagram\.com/([A-Za-z0-9_.]+)/?(?:reels/?)?(?:\?|$)", url)
    if not token or not m or m.group(1) in ("p", "reel", "reels"):
        return []
    api = ("https://api.apify.com/v2/acts/apify~instagram-reel-scraper/run-sync-get-dataset-items"
           f"?token={token}&timeout=280")
    body = json.dumps({"username": [m.group(1)], "resultsLimit": max_items}).encode()
    req = urllib.request.Request(api, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        items = json.load(r)
    vids = []
    for it in items[:max_items]:
        if not it.get("videoUrl"):
            continue
        acc, vid = it.get("ownerUsername") or m.group(1), it.get("shortCode") or it.get("id")
        mp4 = Path(tmp) / f"{acc}__{vid}.mp4"
        urllib.request.urlretrieve(it["videoUrl"], mp4)
        info = {"webpage_url": it.get("url"), "description": it.get("caption"), "like_count": it.get("likesCount"),
                "comment_count": it.get("commentsCount"), "view_count": it.get("videoPlayCount") or it.get("videoViewCount"),
                "upload_date": it.get("timestamp")}
        mp4.with_suffix(".info.json").write_text(json.dumps(info))
        vids.append(mp4)
    print(f"Apify: {len(vids)} Reels von {m.group(1)}")
    return vids


def contact_sheet(video, out_jpg, n=6):
    dur = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)]).stdout or 0)
    frames = []
    for i in range(n):
        t = 0.5 + (dur - 1) * i / max(n - 1, 1)
        p = Path(out_jpg).with_suffix(f".{i}.png")
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
             "-vf", "scale=360:-2", str(p)])
        if p.exists():
            frames.append((t, Image.open(p).convert("RGB")))
            p.unlink()
    if not frames:
        return dur
    w, h = frames[0][1].size
    sheet = Image.new("RGB", (w * len(frames), h), "black")
    for i, (_, im) in enumerate(frames):
        sheet.paste(im.resize((w, h)), (i * w, 0))
    sheet.save(out_jpg, quality=82)
    return dur


GEMINI_PROMPT = """Analysiere dieses Kurzvideo (Reel) als Vorbild für einen eigenen Kanal. Antworte auf Deutsch, knapp, in Stichpunkten:
1. Hook (erste 3 Sekunden): Was passiert in Bild und Ton, warum bleibt man hängen?
2. Storyline: Aufbau, Spannungsbogen, offene Schleifen, Ende/Call-to-Action.
3. Ton und Stimme: Art der Stimme (Mann/Frau, Alter, Tempo, Emotion, KI oder echt), Musik, Soundeffekte.
4. Design: Bildstil, Farben, Schriften, Untertitel, Schnitttempo (ungefähr Schnitte pro 10 s), wiederkehrende Elemente.
5. Was davon sollten wir übernehmen (nur Mechanik und Stil, keine Inhalte)?"""


def gemini_analysis(video):
    key = os.environ.get("GEMINI_API_KEY")
    if not key or video.stat().st_size > 19_000_000:
        return ""
    import base64
    body = {"contents": [{"parts": [{"inlineData": {"mimeType": "video/mp4",
                                                   "data": base64.b64encode(video.read_bytes()).decode()}},
                                    {"text": GEMINI_PROMPT}]}]}
    for model in ("gemini-2.5-flash", "gemini-flash-latest"):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            parts = data["candidates"][0]["content"]["parts"]
            return "\n".join(p.get("text", "") for p in parts if not p.get("thought"))
        except Exception as e:
            print("Gemini-Analyse fehlgeschlagen:", model, str(e)[:200])
    return ""


def transcribe(model, video):
    segs, info = model.transcribe(str(video), vad_filter=True)
    lines = [f"[{s.start:5.1f}s] {s.text.strip()}" for s in segs]
    return info.language, "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--max", type=int, default=5)
    ap.add_argument("--out", default="research")
    a = ap.parse_args()
    from faster_whisper import WhisperModel

    model = WhisperModel("small", device="cpu", compute_type="int8")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for url in a.urls:
        with tempfile.TemporaryDirectory() as tmp:
            vids = download(url, tmp, a.max)
            if not vids:
                try:
                    vids = apify_download(url, tmp, a.max)
                except Exception as e:
                    print("Apify fehlgeschlagen:", e)
            if not vids:
                summary.append(f"- {url}: nichts geladen (Instagram verlangt Login; mit Secret APIFY_TOKEN klappt es über Apify)")
            for v in vids:
                acc, vid = v.stem.split("__", 1)
                d = out / acc
                d.mkdir(parents=True, exist_ok=True)
                info = {}
                ij = v.with_suffix(".info.json")
                if ij.exists():
                    info = json.loads(ij.read_text())
                dur = contact_sheet(v, d / f"{vid}.jpg")
                lang, text = transcribe(model, v)
                md = [f"# {acc} / {vid}", "",
                      f"- URL: {info.get('webpage_url', url)}",
                      f"- Dauer: {dur:.1f} s, Sprache: {lang}",
                      f"- Likes: {info.get('like_count')}, Kommentare: {info.get('comment_count')}, Views: {info.get('view_count')}",
                      f"- Datum: {info.get('upload_date')}", "",
                      "## Beschreibung", "", (info.get("description") or "").strip(), "",
                      "## Transkript", "", text, "",
                      "## Analyse (Gemini sieht und hört das Video)", "", gemini_analysis(v), ""]
                (d / f"{vid}.md").write_text("\n".join(md), encoding="utf-8")
                summary.append(f"- {acc}/{vid}: {dur:.0f} s, {info.get('like_count')} Likes")
    (out / "LETZTER_LAUF.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary))


if __name__ == "__main__":
    main()
