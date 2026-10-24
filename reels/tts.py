"""Text-to-Speech mit Wort-Zeitstempeln.

Backends:
- edge:   Microsoft Edge Online-Stimmen (kostenlos, gute Qualität, liefert Wortzeiten)
- espeak: lokal und offline (robotisch), nur als Notlösung/Test; Wortzeiten werden geschätzt
"""
import asyncio
import json
import subprocess
from pathlib import Path

VOICES = {
    "de": {"edge": "de-DE-ConradNeural", "espeak": "de"},
    "en": {"edge": "en-US-AndrewNeural", "espeak": "en-us"},
    "es": {"edge": "es-ES-AlvaroNeural", "espeak": "es"},
    "pt": {"edge": "pt-BR-AntonioNeural", "espeak": "pt-br"},
    "fr": {"edge": "fr-FR-HenriNeural", "espeak": "fr"},
}


def audio_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def _estimate_words(text, duration):
    """Verteilt die Dauer proportional zur Wortlänge (für Backends ohne Wortzeiten)."""
    words = text.split()
    weights = [len(w) + 2 for w in words]
    total = sum(weights)
    t, out = 0.0, []
    for w, k in zip(words, weights):
        d = duration * k / total
        out.append((t, t + d, w))
        t += d
    return out


async def _edge(text, voice, path, rate):
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words = []
    with open(path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append((start, start + chunk["duration"] / 1e7, chunk["text"]))
    return words


def speak(text, lang, path, backend="edge", rate="+8%"):
    """Erzeugt Audio unter `path` und gibt (dauer, [(start, ende, wort), ...]) zurück."""
    path = Path(path)
    if backend == "edge":
        words = asyncio.run(_edge(text, VOICES[lang]["edge"], path, rate))
        dur = audio_duration(path)
        if not words:
            words = _estimate_words(text, dur)
        return dur, words
    if backend == "espeak":
        wav = path.with_suffix(".wav")
        subprocess.run(["espeak-ng", "-v", VOICES[lang]["espeak"], "-s", "165", "-w", str(wav), text], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), str(path)], check=True)
        dur = audio_duration(path)
        return dur, _estimate_words(text, dur)
    raise ValueError(f"Unbekanntes TTS-Backend: {backend}")
