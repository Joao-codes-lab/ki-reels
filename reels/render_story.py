"""Version 2: ein Teil der Serie „Das Haus der 8 Level“ als Video (1080x1920).

Ablauf eines Teils:
  1. Hook: Haus-Querschnitt, Kamera fährt auf das aktuelle Stockwerk (höhere Etagen verschlossen)
  2. Story: Illustrationen der Figur mit Kamerafahrt, Zahl + Urteil im Bild, Untertitel
  3. Cliffhanger: nächstes Stockwerk leuchtet als „???“ auf, Hinweis auf den nächsten Teil
"""
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from . import tts
from .render import F_BLACK, F_BOLD, F_DISPLAY, F_SEMI, FPS, H, LABELS, W, chunk_words, draw_centered, wrap

XFADE = 0.4
STORY_LABELS = {
    "de": {"part": "TEIL", "next": "Teil {n} kommt morgen", "which": "Welches Haus als Nächstes?", "comment": "Schreib's in die Kommentare"},
    "en": {"part": "PART", "next": "Part {n} drops tomorrow", "which": "Which house next?", "comment": "Tell me in the comments"},
    "es": {"part": "PARTE", "next": "La parte {n} llega mañana", "which": "¿Qué casa sigue?", "comment": "Escríbelo en los comentarios"},
    "pt": {"part": "PARTE", "next": "A parte {n} sai amanhã", "which": "Qual casa vem agora?", "comment": "Escreve nos comentários"},
    "fr": {"part": "PARTIE", "next": "Partie {n} demain", "which": "Quelle maison ensuite ?", "comment": "Dis-le en commentaire"},
}

# Haus-Geometrie (Etage 1 unten, Etage 8 oben)
HX0, HX1, HY_TOP, HY_BOT = 70, 1010, 470, 1830
FLOOR_H = (HY_BOT - HY_TOP) / 8


def _top_shade(h=620):
    """Abdunklung oben, damit Titel und Hinweis auf den nächsten Teil lesbar bleiben."""
    shade = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(shade)
    for y in range(h):
        d.line([(0, y), (W, y)], fill=(5, 6, 16, int(230 * (1 - (y / h) ** 2))))
    return shade


TOP_SHADE = _top_shade()


def floor_box(k):
    y1 = HY_BOT - (k - 1) * FLOOR_H
    return (HX0 + 30, int(y1 - FLOOR_H + 8), HX1 - 30, int(y1 - 8))


def cover(img, w, h):
    """Skaliert und beschneidet ein Bild mittig auf w x h."""
    s = max(w / img.width, h / img.height)
    im = img.resize((int(img.width * s) + 1, int(img.height * s) + 1), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def make_house(floor_imgs, current, reveal_next=False):
    """Querschnitt des Hauses. Etagen über `current` sind verschlossen, Etage 8 bleibt geheim."""
    img = Image.new("RGB", (W, H), (10, 12, 28))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(12 + 18 * t), int(14 + 10 * t), int(34 + 26 * t)))
    # Dach und Fassade
    d.polygon([(HX0 - 20, HY_TOP), (W // 2, HY_TOP - 150), (HX1 + 20, HY_TOP)], fill=(48, 40, 62))
    d.rectangle([HX0, HY_TOP, HX1, HY_BOT + 20], fill=(58, 50, 72))
    for k in range(1, 9):
        box = floor_box(k)
        bw, bh = box[2] - box[0], box[3] - box[1]
        tile = cover(floor_imgs[k - 1], bw, bh) if floor_imgs[k - 1] is not None else Image.new("RGB", (bw, bh), (30, 30, 40))
        locked = k > current
        teaser = reveal_next and k == current + 1
        if locked:
            tile = tile.filter(ImageFilter.GaussianBlur(22 if not teaser else 12))
            tile = ImageEnhance.Brightness(tile).enhance(0.25 if not teaser else 0.7)
        elif k < current:
            tile = ImageEnhance.Brightness(tile).enhance(0.6)
        img.paste(tile, box[:2])
        if locked:
            q = "???" if (k == 8 or (reveal_next and k == current + 1)) else "?"
            f = F_DISPLAY(int(bh * 0.55))
            tw = d.textlength(q, font=f)
            d.text((box[0] + (bw - tw) / 2, box[1] + bh * 0.18), q, font=f, fill=(255, 255, 255, 180))
        f = F_BOLD(30)
        d.rounded_rectangle([box[0] + 10, box[1] + 10, box[0] + 150, box[1] + 52], radius=12, fill=(0, 0, 0))
        d.text((box[0] + 22, box[1] + 13), f"LEVEL {k}", font=f, fill=(255, 255, 255))
    hl = current + 1 if reveal_next and current < 8 else current
    b = floor_box(hl)
    d.rounded_rectangle([b[0] - 8, b[1] - 8, b[2] + 8, b[3] + 8], radius=10, outline=(255, 214, 60), width=8)
    return img


def zoom(img, t, cx, cy, z0, z1):
    """Kamerafahrt: Zoom von z0 auf z1 (t = 0..1) auf den Punkt (cx, cy)."""
    t = t * t * (3 - 2 * t)
    z = z0 + (z1 - z0) * t
    w, h = W / z, H / z
    x = min(max(cx - w / 2, 0), W - w)
    y = min(max(cy - h / 2, 0), H - h)
    return img.crop((int(x), int(y), int(x + w), int(y + h))).resize((W, H), Image.BILINEAR)


def kenburns(img, t, variant):
    """Langsame Fahrt über eine Illustration (Bild ist schon auf 1080x1920 vorbereitet)."""
    z0, z1 = (1.0, 1.14) if variant % 2 == 0 else (1.14, 1.02)
    cx = W / 2 + (40 if variant % 3 == 0 else -40) * (t - 0.5)
    return zoom(img, t, cx, H * 0.45, z0, z1)


def sentence_spans(words):
    """Gibt Indexgrenzen der Sätze in der Wortliste zurück."""
    spans, start = [], 0
    for i, (_, _, w) in enumerate(words):
        if re.search(r"[.!?…]$", w):
            spans.append((start, i))
            start = i + 1
    if start < len(words):
        spans.append((start, len(words) - 1))
    return spans


def draw_badge(d, badge, verdict, y):
    fb, fv = F_BLACK(62), F_BLACK(62)
    t1, t2 = badge.upper() + "  →  ", verdict.upper()
    w1, w2 = d.textlength(t1, font=fb), d.textlength(t2, font=fv)
    tw = w1 + w2
    if tw > W - 100:
        fb = fv = F_BLACK(46)
        w1, w2 = d.textlength(t1, font=fb), d.textlength(t2, font=fv)
        tw = w1 + w2
    x = (W - tw) / 2
    d.rounded_rectangle([x - 28, y - 14, x + tw + 28, y + 80], radius=24, fill=(12, 12, 20))
    d.text((x, y), t1, font=fb, fill=(255, 255, 255))
    d.text((x + w1, y), t2, font=fv, fill=(255, 70, 80))


def draw_captions(d, chunk, t, y=1420):
    fnt = F_BLACK(80)
    words = [w[2] for w in chunk]
    space = d.textlength(" ", font=fnt)
    widths = [d.textlength(w, font=fnt) for w in words]
    total_w = sum(widths) + space * (len(words) - 1)
    if total_w > W - 120:
        fnt = F_BLACK(62)
        space = d.textlength(" ", font=fnt)
        widths = [d.textlength(w, font=fnt) for w in words]
        total_w = sum(widths) + space * (len(words) - 1)
    x = (W - total_w) / 2
    for (a, b, w), ww in zip(chunk, widths):
        active = a <= t < b + 0.05
        d.text((x, y), w, font=fnt, fill=(255, 225, 60) if active else (255, 255, 255),
               stroke_width=9, stroke_fill=(0, 0, 0))
        x += ww + space


def render_part(series, n, images, out_path, backend="edge"):
    """images: {"floors": [8 Bildpfade oder None], "scenes": [Bildpfade für Level n]}"""
    lang = series["lang"]
    lv = series["levels"][n - 1]
    lab, slab = LABELS[lang], STORY_LABELS[lang]
    floors = [Image.open(p).convert("RGB") if p else None for p in images["floors"]]
    scenes = [cover(Image.open(p).convert("RGB"), W, H) for p in images["scenes"]]
    house = make_house(floors, n)
    house_next = make_house(floors, n, reveal_next=True)
    fb = floor_box(n)
    fcx, fcy = (fb[0] + fb[2]) / 2, (fb[1] + fb[3]) / 2

    with tempfile.TemporaryDirectory() as tmp:
        mp3 = Path(tmp) / "voice.mp3"
        dur, words = tts.speak(lv["story"], lang, mp3, backend=backend)
        spans = sentence_spans(words)
        hook_end = words[spans[0][1]][1] if spans else min(3.0, dur)
        hook_end = max(2.5, min(hook_end + 0.2, 5.0))
        # Cliffhanger beginnt mit dem Satz, der etwa 9 s vor Schluss anfängt (Teaser + Verweis auf den nächsten Teil)
        starts = [words[a][0] for a, _ in spans[1:]] or [dur * 0.85]
        cliff_start = min(starts, key=lambda x: abs(x - (dur - 9))) - 0.1
        cliff_start = min(max(cliff_start, hook_end + 6), dur - 3)
        total = dur + 1.6
        chunks = chunk_words(words)

        story_len = cliff_start - hook_end
        seq = scenes + scenes[:1] if len(scenes) > 1 else scenes * 2
        seg = story_len / len(seq)

        def frame(t):
            if t < hook_end:
                img = zoom(house, t / hook_end, fcx, fcy, 1.0, 1.7)
            elif t < cliff_start:
                k = min(int((t - hook_end) / seg), len(seq) - 1)
                lt = (t - hook_end - k * seg) / seg
                img = kenburns(seq[k], lt, k)
                if k > 0 and (t - hook_end - k * seg) < XFADE:
                    prev = kenburns(seq[k - 1], 1.0, k - 1)
                    img = Image.blend(prev, img, (t - hook_end - k * seg) / XFADE)
                if t - hook_end < XFADE:
                    img = Image.blend(zoom(house, 1.0, fcx, fcy, 1.0, 1.7), img, (t - hook_end) / XFADE)
            else:
                lt = min((t - cliff_start) / max(total - cliff_start, 0.1), 1.0)
                tgt = floor_box(min(n + 1, 8))
                img = zoom(house_next, 1 - lt, (tgt[0] + tgt[2]) / 2, (tgt[1] + tgt[3]) / 2, 1.0, 1.35)
            img = img.copy()
            img.paste(TOP_SHADE, (0, 0), TOP_SHADE)
            d = ImageDraw.Draw(img)

            # Kopfzeile: Serie + Level
            d.rounded_rectangle([40, 80, 40 + 330, 150], radius=35, fill=(255, 214, 60))
            d.text((70, 88), f"LEVEL {n}/8", font=F_BLACK(48), fill=(10, 10, 20))
            # dezente KI-Kennzeichnung unten links
            d.text((36, H - 62), lab["ai"], font=F_SEMI(24), fill=(200, 200, 210),
                   stroke_width=2, stroke_fill=(0, 0, 0))
            ft = F_BOLD(56)
            draw_centered(d, wrap(d, series["title"], ft, W - 120), ft, 190, (255, 255, 255),
                          stroke=6, stroke_fill=(0, 0, 0))

            if t < hook_end:
                pass
            elif t < cliff_start:
                draw_badge(d, lv["badge"], lv["verdict"], 1180)
                fn = F_BOLD(44)
                draw_centered(d, [lv["name"]], fn, 1290, (255, 255, 255), stroke=5, stroke_fill=(0, 0, 0))
            else:
                if n < 8:
                    txt = slab["next"].format(n=n + 1)
                    draw_centered(d, [f'{slab["part"]} {n + 1} →'], F_DISPLAY(120), 330, (255, 214, 60),
                                  stroke=8, stroke_fill=(0, 0, 0))
                    draw_centered(d, [txt], F_BOLD(54), 470, (255, 255, 255), stroke=6, stroke_fill=(0, 0, 0))
                else:
                    draw_centered(d, wrap(d, slab["which"], F_DISPLAY(96), W - 120), F_DISPLAY(96), 330,
                                  (255, 214, 60), stroke=8, stroke_fill=(0, 0, 0))
                    draw_centered(d, [slab["comment"]], F_BOLD(54), 560, (255, 255, 255),
                                  stroke=6, stroke_fill=(0, 0, 0))

            cur = None
            for c in chunks:
                if c[0][0] - 0.05 <= t <= c[-1][1] + 0.25:
                    cur = c
            if cur:
                draw_captions(d, cur, t)
            d.rectangle([0, H - 12, int(W * t / total), H], fill=(255, 214, 60))
            return img

        ff = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
             "-r", str(FPS), "-i", "-", "-i", str(mp3), "-filter_complex",
             "[1:a]apad=pad_dur=2,loudnorm=I=-14:TP=-1.5[a]", "-map", "0:v", "-map", "[a]",
             "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.2f}", "-movflags", "+faststart", str(out_path)],
            stdin=subprocess.PIPE,
        )
        try:
            for i in range(int(total * FPS)):
                ff.stdin.write(frame(i / FPS).tobytes())
        except BrokenPipeError:
            pass
        ff.stdin.close()
        ff.wait()
        if ff.returncode:
            raise RuntimeError("ffmpeg ist fehlgeschlagen")
    return {"path": str(out_path), "duration": round(total, 1)}
