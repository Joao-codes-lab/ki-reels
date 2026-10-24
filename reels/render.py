"""Rendert ein Level-Video (9:16, 1080x1920) aus einem Skript-JSON.

Ablauf: Skript -> TTS pro Abschnitt -> Zeitachse -> Frames mit Pillow -> ffmpeg (H.264 + AAC).
Die Grafiken werden komplett selbst erzeugt (keine Stock-Clips), damit die Videos
nicht als Schablonen-Massenware gelten.
"""
import colorsys
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from . import tts

W, H, FPS = 1080, 1920, 30
GAP = 0.35  # Pause nach jedem Abschnitt in Sekunden
ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"

LABELS = {
    "de": {"level": "LEVEL", "ai": "KI-generiert", "follow": "Folgen für Teil 2", "bio": "Link in Bio"},
    "en": {"level": "LEVEL", "ai": "AI-generated", "follow": "Follow for part 2", "bio": "Link in bio"},
    "es": {"level": "NIVEL", "ai": "Generado con IA", "follow": "Sígueme para la parte 2", "bio": "Link en la bio"},
    "pt": {"level": "NÍVEL", "ai": "Gerado por IA", "follow": "Siga para a parte 2", "bio": "Link na bio"},
    "fr": {"level": "NIVEAU", "ai": "Généré par IA", "follow": "Abonne-toi pour la partie 2", "bio": "Lien en bio"},
}


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


F_BLACK = lambda s: font("Inter-Black.otf", s)
F_DISPLAY = lambda s: font("InterDisplay-Black.otf", s)
F_BOLD = lambda s: font("Inter-Bold.otf", s)
F_SEMI = lambda s: font("Inter-SemiBold.otf", s)


PALETTE = [(40, 220, 255), (40, 230, 150), (150, 235, 60), (255, 220, 40),
           (255, 150, 30), (255, 70, 90), (230, 60, 220), (150, 90, 255)]


def level_color(n, total):
    """Farbverlauf von Türkis (Level 1) über Gelb und Rot bis Violett (höchstes Level)."""
    f = 0.0 if total <= 1 else (n - 1) / (total - 1)
    x = f * (len(PALETTE) - 1)
    i = min(int(x), len(PALETTE) - 2)
    t = x - i
    a, b = PALETTE[i], PALETTE[i + 1]
    return tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3))


def wrap(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=fnt) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_centered(draw, lines, fnt, y, fill, spacing=1.15, stroke=0, stroke_fill=(0, 0, 0)):
    asc, desc = fnt.getmetrics()
    lh = int((asc + desc) * spacing)
    for i, line in enumerate(lines):
        tw = draw.textlength(line, font=fnt)
        draw.text(((W - tw) / 2, y + i * lh), line, font=fnt, fill=fill,
                  stroke_width=stroke, stroke_fill=stroke_fill)
    return y + len(lines) * lh


def make_background(color):
    """Dunkler Verlauf mit weichem Farbschein in Level-Farbe."""
    bg = Image.new("RGB", (W, H), (8, 10, 22))
    px = ImageDraw.Draw(bg)
    for y in range(H):
        t = y / H
        px.line([(0, y), (W, y)], fill=(int(8 + 10 * t), int(10 + 6 * t), int(22 + 20 * t)))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W * 0.05, H * 0.2, W * 0.95, H * 0.62], fill=tuple(int(c * 0.55) for c in color))
    glow = glow.filter(ImageFilter.GaussianBlur(180))
    return ImageChops.add(bg, glow)


def chunk_words(words, max_words=3):
    """Gruppiert Wortzeiten zu kurzen Untertitel-Häppchen."""
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or w[2].endswith((".", ",", "!", "?", ":")):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build_segments(script, workdir, backend):
    """Erzeugt Audio pro Abschnitt und gibt die Zeitachse zurück."""
    lang = script["lang"]
    parts = [("hook", None, script["hook"])]
    for lv in script["levels"]:
        parts.append(("level", lv, f'{LABELS[lang]["level"].capitalize()} {lv["n"]}. {lv["name"]}. {lv["text"]}'))
    parts.append(("cta", None, script["cta"]))

    segs, t = [], 0.0
    for i, (kind, lv, text) in enumerate(parts):
        mp3 = Path(workdir) / f"seg{i:02d}.mp3"
        dur, words = tts.speak(text, lang, mp3, backend=backend)
        segs.append({"kind": kind, "level": lv, "text": text, "audio": mp3, "start": t,
                     "dur": dur + GAP, "words": [(t + a, t + b, w) for a, b, w in words]})
        t += dur + GAP
    return segs, t


def build_audio(segs, out_wav):
    """Fügt die Abschnitte mit Pausen zu einer Tonspur zusammen."""
    inputs, filters = [], []
    for i, s in enumerate(segs):
        inputs += ["-i", str(s["audio"])]
        filters.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,apad=pad_dur={GAP}[a{i}]")
    concat = "".join(f"[a{i}]" for i in range(len(segs)))
    fc = ";".join(filters) + f";{concat}concat=n={len(segs)}:v=0:a=1,loudnorm=I=-14:TP=-1.5[out]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", fc,
                    "-map", "[out]", str(out_wav)], check=True)


class Renderer:
    def __init__(self, script):
        self.s = script
        self.lang = script["lang"]
        self.total = len(script["levels"])
        self.bg_cache = {}
        self.layer_cache = {}

    def bg(self, key, color):
        if key not in self.bg_cache:
            self.bg_cache[key] = make_background(color)
        return self.bg_cache[key]

    def static_layer(self, seg):
        """Alles, was sich innerhalb eines Abschnitts nicht bewegt (außer Zahl und Untertitel)."""
        key = id(seg)
        if key in self.layer_cache:
            return self.layer_cache[key]
        lab = LABELS[self.lang]
        if seg["kind"] == "level":
            n = seg["level"]["n"]
            color = level_color(n, self.total)
        elif seg["kind"] == "hook":
            n, color = 0, (90, 200, 255)
        else:
            n, color = self.total, level_color(self.total, self.total)
        img = self.bg(seg["kind"] + str(n), color).copy()
        d = ImageDraw.Draw(img)

        # KI-Kennzeichnung oben rechts
        f = F_SEMI(34)
        tw = d.textlength(lab["ai"], font=f)
        d.rounded_rectangle([W - tw - 90, 90, W - 50, 150], radius=30, outline=(255, 255, 255), width=2)
        d.text((W - tw - 70, 98), lab["ai"], font=f, fill=(255, 255, 255))

        # Serientitel oben
        ft = F_BOLD(58)
        lines = wrap(d, self.s["title"], ft, W - 160)
        draw_centered(d, lines, ft, 200, (255, 255, 255))

        # Level-Leiter rechts
        if seg["kind"] != "hook":
            x0, y_top, y_bot = 55, 560, 1250
            step = (y_bot - y_top) / self.total
            for k in range(self.total, 0, -1):
                y = y_bot - (k) * step
                c = level_color(k, self.total)
                on = k <= n
                d.rounded_rectangle([x0, y + 6, x0 + 40, y + step - 6], radius=10,
                                    fill=c if on else (40, 44, 66))
                if k == n:
                    d.rounded_rectangle([x0 - 8, y - 2, x0 + 48, y + step + 2], radius=14,
                                        outline=(255, 255, 255), width=4)

        if seg["kind"] == "level":
            fl = F_BOLD(80)
            d.text(((W - d.textlength(lab["level"], font=fl)) / 2, 520), lab["level"], font=fl, fill=color)
            fn = F_DISPLAY(96)
            nl = wrap(d, seg["level"]["name"], fn, W - 220)
            draw_centered(d, nl, fn, 1070, (255, 255, 255))
        elif seg["kind"] == "hook":
            fh = F_DISPLAY(150)
            draw_centered(d, ["1 → " + str(self.total)], fh, 640, color)
        else:
            fc = F_DISPLAY(96)
            y = draw_centered(d, wrap(d, lab["follow"], fc, W - 200), fc, 640, (255, 255, 255))
            fb = F_BOLD(70)
            draw_centered(d, [lab["bio"]], fb, y + 40, color)
        self.layer_cache[key] = (img, color, n)
        return self.layer_cache[key]

    def number_img(self, n, color):
        key = ("num", n)
        if key not in self.layer_cache:
            fnt = F_DISPLAY(400)
            txt = str(n)
            tmp = Image.new("RGBA", (700, 520), (0, 0, 0, 0))
            d = ImageDraw.Draw(tmp)
            tw = d.textlength(txt, font=fnt)
            shadow = Image.new("RGBA", tmp.size, (0, 0, 0, 0))
            ImageDraw.Draw(shadow).text(((700 - tw) / 2, 10), txt, font=fnt, fill=color + (255,))
            shadow = shadow.filter(ImageFilter.GaussianBlur(28))
            tmp = Image.alpha_composite(tmp, shadow)
            ImageDraw.Draw(tmp).text(((700 - tw) / 2, 10), txt, font=fnt, fill=(255, 255, 255, 255))
            self.layer_cache[key] = tmp
        return self.layer_cache[key]

    def frame(self, t, segs, total_dur):
        seg = next((s for s in segs if s["start"] <= t < s["start"] + s["dur"]), segs[-1])
        base, color, n = self.static_layer(seg)
        img = base.copy()
        local = t - seg["start"]

        # Pop-in der Level-Zahl
        if seg["kind"] == "level":
            num = self.number_img(n, color)
            if local < 0.12:
                sc = 0.55 + 0.5 * (local / 0.12) * 1.0
            elif local < 0.25:
                sc = 1.05 - 0.05 * ((local - 0.12) / 0.13)
            else:
                sc = 1.0
            nw, nh = int(num.width * sc), int(num.height * sc)
            numr = num.resize((nw, nh), Image.LANCZOS) if sc != 1.0 else num
            img.paste(numr, (int((W - nw) / 2), int(830 - nh / 2 + 60)), numr)

        d = ImageDraw.Draw(img)
        # Untertitel: aktuelles Häppchen, aktives Wort gelb
        chunk = None
        for c in seg.setdefault("_chunks", chunk_words(seg["words"])):
            if c[0][0] - 0.05 <= t <= c[-1][1] + 0.25:
                chunk = c
        if chunk:
            fnt = F_BLACK(84)
            words = [w[2] for w in chunk]
            space = d.textlength(" ", font=fnt)
            widths = [d.textlength(w, font=fnt) for w in words]
            total_w = sum(widths) + space * (len(words) - 1)
            if total_w > W - 120:
                fnt = F_BLACK(66)
                widths = [d.textlength(w, font=fnt) for w in words]
                space = d.textlength(" ", font=fnt)
                total_w = sum(widths) + space * (len(words) - 1)
            x, y = (W - total_w) / 2, 1440
            for (a, b, w), ww in zip(chunk, widths):
                active = a <= t < b + 0.05
                d.text((x, y), w, font=fnt, fill=(255, 225, 60) if active else (255, 255, 255),
                       stroke_width=8, stroke_fill=(0, 0, 0))
                x += ww + space

        # Fortschrittsbalken unten
        d.rectangle([0, H - 14, W, H], fill=(30, 30, 45))
        d.rectangle([0, H - 14, int(W * t / total_dur), H], fill=color)
        return img


def render(script_path, out_path, backend="edge"):
    script = json.loads(Path(script_path).read_text(encoding="utf-8"))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        segs, total = build_segments(script, tmp, backend)
        wav = Path(tmp) / "voice.wav"
        build_audio(segs, wav)
        r = Renderer(script)
        n_frames = int(total * FPS)
        ff = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(wav),
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out_path)],
            stdin=subprocess.PIPE,
        )
        for i in range(n_frames):
            ff.stdin.write(r.frame(i / FPS, segs, total).tobytes())
        ff.stdin.close()
        ff.wait()
        if ff.returncode:
            raise RuntimeError("ffmpeg ist fehlgeschlagen")
    return {"path": str(out_path), "duration": round(total, 1)}
