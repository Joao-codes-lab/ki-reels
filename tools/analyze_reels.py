"""Analysiert öffentliche Reels: Standbilder (Design) + Transkript (Inhalt).

  python tools/analyze_reels.py URL [URL ...] --max 5 --out research

Nutzt yt-dlp (Download) und faster-whisper (Spracherkennung, läuft auf CPU).
Pro Reel entsteht <out>/<account>/<id>.md mit Transkript, Beschreibung, Kennzahlen und
<id>.jpg mit 6 Standbildern. Die Videos selbst werden nicht gespeichert.
"""
import argparse
import json
import subprocess
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
    summary = []
    for url in a.urls:
        with tempfile.TemporaryDirectory() as tmp:
            vids = download(url, tmp, a.max)
            if not vids:
                summary.append(f"- {url}: nichts geladen (evtl. Login nötig)")
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
                      "## Transkript", "", text, ""]
                (d / f"{vid}.md").write_text("\n".join(md), encoding="utf-8")
                summary.append(f"- {acc}/{vid}: {dur:.0f} s, {info.get('like_count')} Likes")
    (out / "LETZTER_LAUF.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary))


if __name__ == "__main__":
    main()
