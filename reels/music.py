"""Hintergrundmusik aus der Bibliothek assets/music (Kevin MacLeod, CC BY 4.0) nach Stimmung.

  bed = music.bed([(0, "luxus"), (31.5, "drama"), (58, "twist")], total)   # mono, sfx.SR
  sfx.write_wav(fx, sfx.mix(events, total, bed=bed))
  caption += "\n" + music.credits()                              # Namensnennung ist Pflicht

Stimmungen: lofi (Signature-Sound 8-Levels), luxus, spannung, drama, twist, gefuehl, komik (siehe bibliothek.json, gebaut von tools/music_library.py).
Die Vorbilder legen die Musik ca. 16-18 dB unter die Stimme, Wechsel weich mit Crossfade.
"""
import json
import random
import subprocess
from pathlib import Path

import numpy as np

from .sfx import SR

DIR = Path(__file__).resolve().parent.parent / "assets" / "music"
LIB = json.loads((DIR / "bibliothek.json").read_text(encoding="utf-8")) if (DIR / "bibliothek.json").exists() else {}
FADE = 1.2  # Sekunden Crossfade bei Stimmungswechsel
USED = []


def pick(mood, seed=None):
    tracks = LIB.get(mood) or LIB.get("spannung") or []
    if not tracks:
        return None
    rnd = random.Random(seed)
    return rnd.choices(tracks, weights=[max(t["score"], 1) for t in tracks])[0]


def _load(track, sec):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(track.get("start", 0)), "-i",
                          str(DIR / track["file"]), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    if not len(a):
        return np.zeros(int(sec * SR))
    a /= max(np.sqrt(np.mean(a ** 2)), 1e-4) * 8  # auf gleiche Lautheit (RMS ~0.125) bringen
    n = int(sec * SR)
    return np.tile(a, n // len(a) + 1)[:n]


def bed(segments, total, gain=0.16, seed=None):
    """segments: [(start_s, stimmung)], aufsteigend. Gibt Musikbett (mono) über total Sekunden zurück."""
    USED.clear()
    n = int(total * SR)
    out = np.zeros(n)
    f = int(FADE * SR)
    for i, (start, mood) in enumerate(segments):
        end = segments[i + 1][0] if i + 1 < len(segments) else total
        track = pick(mood, seed=None if seed is None else f"{seed}-{i}")
        if not track:
            continue
        USED.append(track["credit"])
        a, b = int(start * SR), min(int(end * SR) + f, n)  # überlappt in den nächsten Abschnitt
        seg = _load(track, (b - a) / SR)
        env = np.ones(b - a)
        if i:
            env[:f] = np.linspace(0, 1, min(f, b - a))
        if b < n:
            env[-f:] = np.linspace(1, 0, f)
        out[a:b] += seg[: b - a] * env
    fade = np.minimum(1, np.minimum(np.arange(n) / (SR * 0.8), (n - np.arange(n)) / (SR * 1.5)))
    return out * fade * gain


def credits():
    """Namensnennung für die zuletzt mit bed() verwendeten Titel (gehört in die Caption)."""
    return " · ".join(dict.fromkeys(USED))
