"""Erzeugt Hörproben verschiedener kostenloser Stimmen: python tools/voice_samples.py --out research/stimmen"""
import argparse
import asyncio
import base64
import json
import os
import subprocess
import urllib.request
import wave
from pathlib import Path

TEXT_DE = ("Level drei: achtzigtausend Euro im Jahr, und trotzdem pleite. Markus ist vierunddreißig, "
           "Ingenieur in München. Von außen sieht alles perfekt aus. Aber jeden Monat, am Fünfundzwanzigsten, "
           "schaut er auf sein Konto und spürt diesen Druck in der Brust. Wie kann das sein?")
TEXT_EN = ("Level three: eighty thousand dollars a year, and still broke. Mark is thirty-four, an engineer in "
           "New York. From the outside, everything looks perfect. But every month, on the twenty-fifth, he checks "
           "his account and feels that tightness in his chest. How is that even possible?")

EDGE = {"de": ["de-DE-FlorianMultilingualNeural", "de-DE-SeraphinaMultilingualNeural", "de-DE-ConradNeural",
               "de-DE-KillianNeural"],
        "en": ["en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural", "en-US-AvaMultilingualNeural"]}
GEMINI_VOICES = ["Charon", "Puck", "Fenrir", "Orus", "Kore", "Aoede"]
GEMINI_TTS_MODELS = ["gemini-2.5-flash-preview-tts", "gemini-2.5-flash-tts", "gemini-2.5-pro-preview-tts"]
STYLE = {"de": "Erzähle das wie ein spannender Storyteller in einem viralen Kurzvideo: natürlich, warm, mit Pausen "
               "und echter Emotion, nicht wie eine Nachrichtensprecherin: ",
         "en": "Narrate this like a gripping storyteller in a viral short video: natural, warm, with pauses and real "
               "emotion, not like a news anchor: "}


async def edge(text, voice, path, rate):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate).save(str(path))


def gemini(text, voice, path):
    key = os.environ["GEMINI_API_KEY"]
    body = {"contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    err = None
    for m in GEMINI_TTS_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
        req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.load(r)
            pcm = base64.b64decode(data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
            wav = path.with_suffix(".wav")
            with wave.open(str(wav), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "128k", str(path)], check=True)
            wav.unlink()
            return m
        except Exception as e:
            err = f"{m}: {e}"
    raise RuntimeError(err)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="research/stimmen")
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    log = []
    for lang, text in (("de", TEXT_DE), ("en", TEXT_EN)):
        for v in EDGE[lang]:
            p = out / f"{lang}_edge_{v.split('-')[2]}.mp3"
            try:
                asyncio.run(edge(text, v, p, "+5%"))
                log.append(f"ok  {p.name}")
            except Exception as e:
                log.append(f"ERR {p.name}: {e}")
        for v in GEMINI_VOICES:
            p = out / f"{lang}_gemini_{v}.mp3"
            try:
                m = gemini(STYLE[lang] + text, v, p)
                log.append(f"ok  {p.name} ({m})")
            except Exception as e:
                log.append(f"ERR {p.name}: {str(e)[:200]}")
    (out / "LOG.txt").write_text("\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()
