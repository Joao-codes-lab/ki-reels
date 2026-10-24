"""Erzeugt ein Video aus einem Skript: python make_video.py content/x.json [--tts edge|espeak]"""
import argparse
from pathlib import Path

from reels.render import render

ap = argparse.ArgumentParser()
ap.add_argument("script")
ap.add_argument("--tts", default="edge")
ap.add_argument("--out", default=None)
a = ap.parse_args()
out = a.out or f"out/{Path(a.script).stem}.mp4"
print(render(a.script, out, backend=a.tts))
