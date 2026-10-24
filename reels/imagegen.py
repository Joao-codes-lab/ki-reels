"""Bilder per kostenloser Bild-KI erzeugen.

Reihenfolge der Anbieter:
1. Gemini-Bildmodell (mit GEMINI_API_KEY, sofern das Kontingent reicht)
2. Pollinations.ai (kostenlos, ohne Schlüssel; optional POLLINATIONS_TOKEN für höhere Limits)
Schlägt alles fehl, entsteht ein schlichtes Ersatzbild, damit der Lauf nicht abbricht.
"""
import base64
import json
import os
import random
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

STYLE = (
    "flat 2D cartoon illustration, bold clean dark outlines, simple round-faced cartoon characters "
    "with big expressive eyes and eyebrows, rich detailed background, cinematic warm lighting, "
    "vibrant but harmonious colors, high detail, comic book style, no text, no letters, no watermark"
)

GEMINI_IMAGE_MODELS = [m for m in (os.environ.get("GEMINI_IMAGE_MODEL"), "gemini-2.5-flash-image") if m]
_last_pollinations = [0.0]


def _gemini(prompt, w, h):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("kein GEMINI_API_KEY")
    aspect = "9:16" if h > w * 1.3 else ("16:9" if w > h * 1.3 else "1:1")
    body = {"contents": [{"parts": [{"text": f"{prompt}. Style: {STYLE}. Aspect ratio {aspect}."}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect}}}
    last = None
    for model in dict.fromkeys(GEMINI_IMAGE_MODELS):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.load(r)
            for part in data["candidates"][0]["content"]["parts"]:
                if "inlineData" in part:
                    return base64.b64decode(part["inlineData"]["data"])
            last = RuntimeError("keine Bilddaten in der Antwort")
        except Exception as e:
            last = e
    raise last


def _pollinations(prompt, w, h, seed):
    wait = 16 - (time.time() - _last_pollinations[0])  # anonyme Nutzung: höchstens ca. 1 Bild pro 15 s
    if wait > 0:
        time.sleep(wait)
    q = urllib.parse.quote(f"{prompt}. {STYLE}")
    params = {"width": w, "height": h, "seed": seed, "model": "flux", "nologo": "true", "private": "true"}
    url = f"https://image.pollinations.ai/prompt/{q}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": "ki-reels/1.0"}
    if os.environ.get("POLLINATIONS_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['POLLINATIONS_TOKEN']}"
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=240) as r:
                data = r.read()
            _last_pollinations[0] = time.time()
            if len(data) > 5000:
                return data
            last = RuntimeError(f"Antwort zu klein ({len(data)} Bytes)")
        except Exception as e:
            last = e
        time.sleep(20 * (attempt + 1))
    raise last


def _placeholder(path, w, h, prompt):
    img = Image.new("RGB", (w, h), (30, 34, 60))
    d = ImageDraw.Draw(img)
    rnd = random.Random(prompt)
    for _ in range(14):
        x, y, r = rnd.randint(0, w), rnd.randint(0, h), rnd.randint(w // 10, w // 3)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(rnd.randint(40, 120), rnd.randint(40, 120), rnd.randint(90, 200)))
    img.filter(ImageFilter.GaussianBlur(40)).save(path)


def generate(prompt, path, w=768, h=1344, seed=None):
    """Erzeugt ein Bild unter `path` (PNG/JPG) und gibt den Namen des Anbieters zurück."""
    path = Path(path)
    marker = path.with_name(path.name + ".ersatz")
    if path.exists() and path.stat().st_size > 5000 and not marker.exists():
        return "cache"
    path.parent.mkdir(parents=True, exist_ok=True)
    seed = seed if seed is not None else random.randint(1, 10**6)
    order = os.environ.get("IMAGE_PROVIDERS", "gemini,pollinations").split(",")
    errors = []
    for name in order:
        try:
            data = _gemini(prompt, w, h) if name == "gemini" else _pollinations(prompt, w, h, seed)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            Image.open(tmp).convert("RGB").resize((w, h), Image.LANCZOS).save(path)
            tmp.unlink()
            marker.unlink(missing_ok=True)
            return name
        except Exception as e:
            errors.append(f"{name}: {e}")
    print("  Bild-KI nicht erreichbar, Ersatzbild:", "; ".join(errors)[:300])
    _placeholder(path, w, h, prompt)
    marker.touch()  # beim nächsten Lauf erneut versuchen
    return "placeholder"
