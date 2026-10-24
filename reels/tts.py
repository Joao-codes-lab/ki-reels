"""Text-to-Speech mit Wort-Zeitstempeln.

Backends:
- gemini: Gemini-TTS (kostenlos im free tier, sehr natürlich); Wortzeiten per faster-whisper,
          bei Fehlern automatisch Rückfall auf edge
- edge:   Microsoft Edge Online-Stimmen (kostenlos, gute Qualität, liefert Wortzeiten)
- espeak: lokal und offline (robotisch), nur als Notlösung/Test; Wortzeiten werden geschätzt
"""
import asyncio
import base64
import difflib
import json
import os
import re
import subprocess
import urllib.request
import wave
from pathlib import Path

VOICES = {
    "de": {"edge": "de-DE-FlorianMultilingualNeural", "espeak": "de", "gemini": "Puck"},
    "en": {"edge": "en-US-AndrewMultilingualNeural", "espeak": "en-us", "gemini": "Puck"},
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


def _restore_punctuation(text, words):
    """Edge liefert Wörter ohne Satzzeichen; hängt sie aus dem Originaltext wieder an."""
    out, pos = [], 0
    for start, end, w in words:
        i = text.find(w, pos)
        if i < 0:
            out.append((start, end, w))
            continue
        j = i + len(w)
        k = j
        while k < len(text) and not text[k].isspace() and not text[k].isalnum():
            k += 1
        out.append((start, end, text[i:k]))
        pos = k
    return out


GEMINI_TTS_MODELS = ["gemini-2.5-flash-preview-tts", "gemini-2.5-flash-tts"]
GEMINI_STYLE = {
    "de": "Erzähle lebendig und natürlich wie ein packender Storyteller, mit Emotion und kurzen Pausen: ",
    "en": "Narrate vividly and naturally like a gripping storyteller, with emotion and short pauses: ",
}
_whisper = []


def _gemini(text, lang, path):
    key = os.environ["GEMINI_API_KEY"]
    voice = os.environ.get("GEMINI_VOICE") or VOICES.get(lang, {}).get("gemini", "Puck")
    body = {"contents": [{"parts": [{"text": GEMINI_STYLE.get(lang, GEMINI_STYLE["en"]) + text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    err = None
    for m in GEMINI_TTS_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
        req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                data = json.load(r)
            pcm = base64.b64decode(data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
            break
        except Exception as e:
            err = e
    else:
        raise RuntimeError(f"Gemini-TTS: {err}")
    wav = path.with_suffix(".raw.wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
    # lange Pausen kürzen (auch Stille am Ende) und leicht beschleunigen, damit es nach Reel klingt
    af = ("silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:stop_duration=0.45:"
          "stop_threshold=-45dB,atempo=1.08")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af", af, "-b:a", "160k", str(path)],
                   check=True)
    wav.unlink()


def _norm(w):
    return re.sub(r"[^\w]", "", w.lower())


def _align(text, path, lang):
    """Wortzeiten per faster-whisper erkennen und auf die Wörter des Skripts übertragen."""
    from faster_whisper import WhisperModel

    if not _whisper:
        _whisper.append(WhisperModel(os.environ.get("WHISPER_MODEL", "base"), device="cpu", compute_type="int8"))
    import numpy as np  # Audio selbst dekodieren (PyAV-Versionen in faster-whisper sind wackelig)

    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    segs, _ = _whisper[0].transcribe(audio, language=lang, word_timestamps=True, vad_filter=False)
    heard = [(w.start, w.end, w.word.strip()) for s in segs for w in (s.words or [])]
    script = text.split()
    times = [None] * len(script)
    sm = difflib.SequenceMatcher(None, [_norm(w) for w in script], [_norm(h[2]) for h in heard], autojunk=False)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            times[a + k] = heard[b + k][:2]
    dur = audio_duration(path)
    # Lücken (z. B. Zahlen, die anders erkannt wurden) gleichmäßig auffüllen
    i = 0
    while i < len(script):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(script) and times[j] is None:
            j += 1
        t0 = times[i - 1][1] if i > 0 else 0.0
        t1 = times[j][0] if j < len(script) else dur
        step = max(t1 - t0, 0.05) / (j - i)
        for k in range(i, j):
            times[k] = (t0 + (k - i) * step, t0 + (k - i + 1) * step)
        i = j
    matched = sum(size for _, _, size in sm.get_matching_blocks())
    print(f"  Wortzeiten: {matched}/{len(script)} Wörter erkannt")
    return [(t[0], t[1], w) for t, w in zip(times, script)]


def speak(text, lang, path, backend="edge", rate="+8%"):
    """Erzeugt Audio unter `path` und gibt (dauer, [(start, ende, wort), ...]) zurück."""
    path = Path(path)
    if backend == "gemini":
        try:
            _gemini(text, lang, path)
            return audio_duration(path), _align(text, path, lang)
        except Exception as e:
            print(f"  Gemini-Stimme nicht verfügbar ({str(e)[:160]}), nehme Edge")
            backend = "edge"
    if backend == "edge":
        words = asyncio.run(_edge(text, VOICES[lang]["edge"], path, rate))
        dur = audio_duration(path)
        words = _restore_punctuation(text, words) if words else _estimate_words(text, dur)
        return dur, words
    if backend == "espeak":
        wav = path.with_suffix(".wav")
        subprocess.run(["espeak-ng", "-v", VOICES[lang]["espeak"], "-s", "165", "-w", str(wav), text], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), str(path)], check=True)
        dur = audio_duration(path)
        return dur, _estimate_words(text, dur)
    raise ValueError(f"Unbekanntes TTS-Backend: {backend}")
