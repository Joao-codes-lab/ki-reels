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
    "detailed hand-drawn ink illustration with warm cozy lighting and muted earthy colors, richly detailed "
    "cluttered background, cross-hatching, graphic-novel quality; the character is a simple cartoon figure with a "
    "plain round cream-white ball head without nose, small dot eyes and expressive eyebrows, normal body with "
    "detailed clothes; character drawn clean and simple, background detailed; no text, no letters, no watermark"
)

GEMINI_IMAGE_MODELS = [m for m in (os.environ.get("GEMINI_IMAGE_MODEL"), "gemini-2.5-flash-image") if m]
_last_pollinations = [0.0]


def _gemini(prompt, w, h, style=STYLE):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("kein GEMINI_API_KEY")
    aspect = "9:16" if h > w * 1.3 else ("16:9" if w > h * 1.3 else "1:1")
    body = {"contents": [{"parts": [{"text": f"{prompt}. Style: {style}. Aspect ratio {aspect}."}]}],
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


def _pollinations(prompt, w, h, seed, style=STYLE, model=None):
    """Stil steht VOR dem Inhalt (Bildmodelle gewichten den Anfang am stärksten), Prompt wird gekürzt."""
    wait = 16 - (time.time() - _last_pollinations[0])  # anonyme Nutzung: höchstens ca. 1 Bild pro 15 s
    if wait > 0 and not os.environ.get("POLLINATIONS_TOKEN"):
        time.sleep(wait)
    text = f"{style}. {prompt}"
    q = urllib.parse.quote(text[:900])
    params = {"width": w, "height": h, "seed": seed, "model": model or os.environ.get("POLLINATIONS_MODEL", "flux"),
              "nologo": "true", "private": "true", "enhance": "false"}
    headers = {"User-Agent": "ki-reels/1.0"}
    urls = []
    if os.environ.get("POLLINATIONS_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['POLLINATIONS_TOKEN']}"
        urls.append(f"https://gen.pollinations.ai/image/{q}?{urllib.parse.urlencode(params)}")
    urls.append(f"https://image.pollinations.ai/prompt/{q}?{urllib.parse.urlencode(params)}")
    last = None
    for attempt in range(4):
        for url in urls:
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=240) as r:
                    data = r.read()
                _last_pollinations[0] = time.time()
                if len(data) > 5000:
                    if "image.pollinations.ai" in url and len(urls) > 1:
                        print(f"    Achtung: Bild kommt vom alten Endpunkt (schwächeres Modell), gen-Fehler: {last}")
                    return data
                last = RuntimeError(f"Antwort zu klein ({len(data)} Bytes)")
            except Exception as e:
                last = e
                if hasattr(e, "read"):
                    try:
                        last = RuntimeError(f"{e} {e.read()[:200]!r}")
                    except Exception:
                        pass
        time.sleep(15 * (attempt + 1))
    raise last


def _placeholder(path, w, h, prompt):
    img = Image.new("RGB", (w, h), (30, 34, 60))
    d = ImageDraw.Draw(img)
    rnd = random.Random(prompt)
    for _ in range(14):
        x, y, r = rnd.randint(0, w), rnd.randint(0, h), rnd.randint(w // 10, w // 3)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(rnd.randint(40, 120), rnd.randint(40, 120), rnd.randint(90, 200)))
    img.filter(ImageFilter.GaussianBlur(40)).save(path)


def generate(prompt, path, w=768, h=1344, seed=None, style=None, model=None):
    """Erzeugt ein Bild unter `path` (PNG/JPG) und gibt den Namen des Anbieters zurück."""
    path = Path(path)
    marker = path.with_name(path.name + ".ersatz")
    if path.exists() and path.stat().st_size > 5000 and not marker.exists():
        return "cache"
    path.parent.mkdir(parents=True, exist_ok=True)
    seed = seed if seed is not None else random.randint(1, 10**6)
    order = os.environ.get("IMAGE_PROVIDERS", "pollinations,gemini").split(",")
    errors = []
    for name in order:
        try:
            st = style or STYLE
            data = _gemini(prompt, w, h, st) if name == "gemini" else _pollinations(prompt, w, h, seed, st, model)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            im = Image.open(tmp).convert("RGB")
            if name == "pollinations":  # Wasserzeichen am unteren Rand abschneiden
                im = im.crop((0, 0, im.width, int(im.height * 0.94)))
            cover = max(w / im.width, h / im.height)
            im = im.resize((int(im.width * cover) + 1, int(im.height * cover) + 1), Image.LANCZOS)
            x, y = (im.width - w) // 2, (im.height - h) // 2
            im.crop((x, y, x + w, y + h)).save(path)
            tmp.unlink()
            marker.unlink(missing_ok=True)
            return name
        except Exception as e:
            errors.append(f"{name}: {e}")
    print("  Bild-KI nicht erreichbar, Ersatzbild:", "; ".join(errors)[:300])
    _placeholder(path, w, h, prompt)
    marker.touch()  # beim nächsten Lauf erneut versuchen
    return "placeholder"
