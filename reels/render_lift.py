"""Version 3: „Der Level-Aufzug“ – ein Teil einer 8-teiligen Serie als Video (1080x1920).

Wiedererkennung: Jedes Video beginnt mit geschlossenen Aufzugtüren und der Etagenanzeige,
„Ding“, die Türen gehen auf und die Geschichte des Levels beginnt. Am Ende schließen sich die
Türen, die Anzeige springt auf das nächste Level und es fällt immer derselbe Satz:
„Das siehst du in Level X.“

Tempo („Dopamin“): Bildwechsel alle ~2,3 s mit Zoom-Punch, Blitz und Whoosh, Zahl + Urteil
ploppen mit Ton ins Bild, Untertitel Wort für Wort, leiser Beat darunter.
"""
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import sfx, tts
from .render import F_BLACK, F_BOLD, F_DISPLAY, F_SEMI, FPS, H, LABELS, W, chunk_words, draw_centered, wrap

AMBER = (255, 190, 40)
# Sicherer Bereich: rechts liegen bei TikTok/Reels die Buttons, unten die Beschreibung
SAFE_X0, SAFE_X1, SAFE_BOTTOM = 60, 940, 1640
SAFE_W, SAFE_CX = SAFE_X1 - SAFE_X0, (SAFE_X0 + SAFE_X1) / 2
YELLOW = (255, 225, 60)
CUT = 2.3          # Sekunden pro Bild
DOOR_OPEN = (0.55, 1.15)
LIFT_LABELS = {
    "de": {"next": "Teil {n} kommt morgen", "which": "Welcher Aufzug als Nächstes?", "comment": "Schreib's in die Kommentare"},
    "en": {"next": "Part {n} drops tomorrow", "which": "Which elevator next?", "comment": "Tell me in the comments"},
    "es": {"next": "La parte {n} llega mañana", "which": "¿Qué ascensor sigue?", "comment": "Escríbelo en los comentarios"},
    "pt": {"next": "A parte {n} sai amanhã", "which": "Qual elevador agora?", "comment": "Escreve nos comentários"},
    "fr": {"next": "Partie {n} demain", "which": "Quel ascenseur ensuite ?", "comment": "Dis-le en commentaire"},
}


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def cover(img, w, h):
    s = max(w / img.width, h / img.height)
    im = img.resize((int(img.width * s) + 1, int(img.height * s) + 1), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def view(img, z, cx, cy):
    w, h = W / z, H / z
    x = min(max(cx - w / 2, 0), W - w)
    y = min(max(cy - h / 2, 0), H - h)
    return img.crop((int(x), int(y), int(x + w), int(y + h))).resize((W, H), Image.BILINEAR)


# Bildausschnitte pro Schnitt: Totale, Nah oben, links, rechts
FRAMINGS = [(1.0, 0.5, 0.5), (1.35, 0.5, 0.36), (1.18, 0.38, 0.5), (1.18, 0.62, 0.5)]


def shot(img, k, lt):
    z, fx, fy = FRAMINGS[k % len(FRAMINGS)]
    punch = 0.14 * (1 - ease(lt / 0.08)) if lt < 0.08 else 0  # schneller Zoom-Punch am Schnitt
    drift = 0.06 * lt
    return view(img, z + punch + drift, W * fx, H * fy)


def make_doors(label, sub=None):
    """Zwei Stahltüren (links/rechts), über die Fuge läuft die große Levelnummer."""
    full = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(full)
    for x in range(W):
        g = 120 + int(35 * abs(((x % (W // 2)) / (W / 2)) - 0.5) * -2 + 35)
        d.line([(x, 0), (x, H)], fill=(g - 10, g - 4, g + 6))
    for y in range(0, H, 6):  # gebürsteter Stahl
        d.line([(0, y), (W, y)], fill=(150, 156, 168) if (y // 6) % 3 == 0 else (128, 134, 146))
    d.rectangle([0, 0, W, 40], fill=(40, 42, 50))
    d.rectangle([0, H - 40, W, H], fill=(40, 42, 50))
    d.line([(W // 2, 0), (W // 2, H)], fill=(30, 30, 36), width=10)
    f = F_DISPLAY(560 if len(label) <= 1 else 400)
    tw = d.textlength(label, font=f)
    d.text(((W - tw) / 2, H * 0.30), label, font=f, fill=(255, 205, 60), stroke_width=14, stroke_fill=(25, 25, 30))
    if sub:
        fs = F_BLACK(64)
        sw = d.textlength(sub, font=fs)
        d.text(((W - sw) / 2, H * 0.30 + 560), sub, font=fs, fill=(25, 25, 30))
    return full.crop((0, 0, W // 2, H)), full.crop((W // 2, 0, W, H))


def draw_doors(img, doors, open_frac):
    left, right = doors
    off = int(ease(open_frac) * (W // 2 + 20))
    if off < W // 2:
        img.paste(left, (-off, 0))
        img.paste(right, (W // 2 + off, 0))
        if off > 0:  # Schatten an der Türkante
            d = ImageDraw.Draw(img)
            d.rectangle([W // 2 - off - 6, 0, W // 2 - off, H], fill=(20, 20, 24))
            d.rectangle([W // 2 + off, 0, W // 2 + off + 6, H], fill=(20, 20, 24))


def draw_indicator(img, shown, n_current, title, blink=False):
    """Etagenanzeige oben + Level-Leiste 1-8."""
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([330, 60, 750, 250], radius=28, fill=(12, 12, 16), outline=(70, 70, 80), width=6)
    d.text((370, 82), "LEVEL", font=F_BLACK(36), fill=(150, 110, 30))
    d.text((372, 128), "▲", font=F_BLACK(70), fill=AMBER)
    if not blink:
        num = str(shown)
        f = F_DISPLAY(150)
        tw = d.textlength(num, font=f)
        d.text((640 - tw / 2, 70), num, font=f, fill=AMBER)
    # Leiste mit 8 Knöpfen
    x0, y, step, r = W / 2 - 3.5 * 92, 300, 92, 32
    for k in range(1, 9):
        cx = x0 + (k - 1) * step
        if k < n_current:
            d.ellipse([cx - r, y - r, cx + r, y + r], fill=(120, 90, 25), outline=(20, 20, 20), width=4)
        elif k == n_current:
            d.ellipse([cx - r - 8, y - r - 8, cx + r + 8, y + r + 8], fill=AMBER, outline=(255, 255, 255), width=6)
        else:
            d.ellipse([cx - r, y - r, cx + r, y + r], fill=(30, 30, 38), outline=(110, 110, 120), width=4)
        lab = "?" if (k == 8 and n_current < 8) else str(k)
        f = F_BLACK(34)
        tw = d.textlength(lab, font=f)
        d.text((cx - tw / 2, y - 21), lab, font=f, fill=(15, 15, 15) if k <= n_current else (200, 200, 210))
    ft = F_BOLD(42)
    draw_centered(d, wrap(d, title, ft, W - 200)[:2], ft, 360, (255, 255, 255), stroke=6, stroke_fill=(0, 0, 0))


def badge_image(badge, verdict, name):
    fb = F_BLACK(66)
    t1, t2 = badge.upper() + "  →  ", verdict.upper()
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    w1, w2 = tmp.textlength(t1, font=fb), tmp.textlength(t2, font=fb)
    size = 66
    while w1 + w2 > SAFE_W - 80 and size > 30:
        size -= 4
        fb = F_BLACK(size)
        w1, w2 = tmp.textlength(t1, font=fb), tmp.textlength(t2, font=fb)
    fn = fit_font(tmp, name, F_BOLD, 44, SAFE_W - 80)
    wn = tmp.textlength(name, font=fn)
    bw = int(max(w1 + w2, wn) + 70)
    im = Image.new("RGBA", (bw, 190), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, bw - 1, 104], radius=26, fill=(14, 14, 22, 240), outline=AMBER + (255,), width=5)
    x = (bw - w1 - w2) / 2
    d.text((x, 16), t1, font=fb, fill=(255, 255, 255))
    d.text((x + w1, 16), t2, font=fb, fill=(255, 70, 80))
    d.text(((bw - wn) / 2, 122), name, font=fn, fill=(255, 255, 255), stroke_width=5, stroke_fill=(0, 0, 0))
    return im


def paste_scaled(img, overlay, cx, cy, s):
    if s <= 0.02:
        return
    ov = overlay.resize((max(1, int(overlay.width * s)), max(1, int(overlay.height * s))), Image.BILINEAR)
    img.paste(ov, (int(cx - ov.width / 2), int(cy - ov.height / 2)), ov)


def pop_scale(dt):
    """Plopp-Animation: 0 -> 1.15 -> 1.0 in 0,25 s."""
    if dt < 0:
        return 0
    if dt < 0.15:
        return 1.15 * ease(dt / 0.15)
    if dt < 0.25:
        return 1.15 - 0.15 * ease((dt - 0.15) / 0.1)
    return 1.0


def fit_font(d, text, make, size, max_w, min_size=34):
    """Größte Schrift, bei der `text` in `max_w` passt."""
    while size > min_size and d.textlength(text, font=make(size)) > max_w:
        size -= 4
    return make(size)


def draw_captions(d, chunk, t, y=1480):
    words = [w[2] for w in chunk]
    fnt = fit_font(d, " ".join(words), F_BLACK, 84, SAFE_W - 20)
    space = d.textlength(" ", font=fnt)
    widths = [d.textlength(w, font=fnt) for w in words]
    total_w = sum(widths) + space * (len(words) - 1)
    x = SAFE_CX - total_w / 2
    for (a, b, w), ww in zip(chunk, widths):
        active = a <= t < b + 0.05
        d.text((x, y), w, font=fnt, fill=YELLOW if active else (255, 255, 255), stroke_width=10, stroke_fill=(0, 0, 0))
        x += ww + space


def sentence_starts(words):
    starts, new = [], True
    for i, (_, _, w) in enumerate(words):
        if new:
            starts.append(i)
        new = bool(re.search(r"[.!?…]$", w))
    return starts


def render_part(series, n, images, out_path, backend="gemini"):
    """images: Liste von Bildpfaden für Level n (Hauptbild + Szenen)."""
    lang = series["lang"]
    lv = series["levels"][n - 1]
    lab, ll = LABELS[lang], LIFT_LABELS[lang]
    pics = [cover(Image.open(p).convert("RGB"), W, H) for p in images]
    doors_now = make_doors(str(n))
    last = n >= 8
    doors_next = make_doors("?" if last else str(n + 1))
    badge = badge_image(lv["badge"], lv["verdict"], lv["name"])

    with tempfile.TemporaryDirectory() as tmp:
        voice = Path(tmp) / "voice.mp3"
        dur, words = tts.speak(lv["story"], lang, voice, backend=backend)
        starts = sentence_starts(words)
        # Outro = letzter Satz („Das siehst du in Level X.“), Türen schließen kurz davor
        outro = words[starts[-1]][0] - 0.25 if len(starts) > 1 else dur - 2.5
        outro = min(max(outro, 8.0), dur - 1.5)
        badge_at = words[starts[1]][0] if len(starts) > 1 else 2.5
        badge_at = max(badge_at, DOOR_OPEN[1] + 0.3)
        total = dur + 1.4
        chunks = chunk_words(words)

        cuts = []  # Startzeiten der Schnitte
        t = DOOR_OPEN[0]
        while t < outro:
            cuts.append(t)
            t += CUT
        events = [(0.05, "tick"), (0.2, "tick"), (0.35, "tick"), (DOOR_OPEN[0] - 0.1, "ding")]
        events += [(c, "whoosh") for c in cuts[1:]]
        events += [(badge_at, "pop"), (outro, "whoosh"), (outro + 0.55, "tick"), (outro + 0.7, "tick"),
                   (total - 1.0, "ding")]
        fx = Path(tmp) / "fx.wav"
        sfx.write_wav(fx, sfx.mix(events, total))

        def frame(t):
            if t < outro:
                k = max(i for i, c in enumerate(cuts) if c <= t) if t >= cuts[0] else 0
                c0 = cuts[k] if t >= cuts[0] else 0
                c1 = cuts[k + 1] if k + 1 < len(cuts) else outro
                img = shot(pics[k % len(pics)], k, (t - c0) / max(c1 - c0, 0.1))
                if k > 0 and t - c0 < 0.07:  # kurzer Blitz am Schnitt
                    img = Image.blend(img, Image.new("RGB", (W, H), (255, 255, 255)), 0.35 * (1 - (t - c0) / 0.07))
                if t < DOOR_OPEN[1]:
                    draw_doors(img, doors_now, (t - DOOR_OPEN[0]) / (DOOR_OPEN[1] - DOOR_OPEN[0]))
                shown, blink = n, False
                if t < DOOR_OPEN[0] and n > 1:
                    shown = n - 1 if t < 0.3 else n
            else:
                lt = (t - outro) / 0.5
                k = len(cuts) - 1
                img = shot(pics[k % len(pics)], k, 1.0)
                draw_doors(img, doors_next, 1 - min(lt, 1))
                shown = n if last else n + 1
                blink = (not last) and lt > 1 and int(t * 4) % 2 == 0
            d = ImageDraw.Draw(img)
            draw_indicator(img, shown, n if t < outro + 0.6 else min(n + 1, 8), series["title"], blink)
            if badge_at <= t < outro:
                paste_scaled(img, badge, SAFE_CX, 1255, pop_scale(t - badge_at))
            if t >= outro + 0.5:
                if last:
                    draw_centered(d, wrap(d, ll["which"], F_DISPLAY(90), SAFE_W), F_DISPLAY(90), 1150, YELLOW,
                                  stroke=8, stroke_fill=(0, 0, 0))
                    draw_centered(d, [ll["comment"]], fit_font(d, ll["comment"], F_BOLD, 52, SAFE_W), 1360, (255, 255, 255), stroke=6, stroke_fill=(0, 0, 0))
                else:
                    nxt = ll["next"].format(n=n + 1)
                    draw_centered(d, [nxt], fit_font(d, nxt, F_BOLD, 54, SAFE_W), 1330, (255, 255, 255),
                                  stroke=6, stroke_fill=(0, 0, 0))
            cur = None
            for c in chunks:
                if c[0][0] - 0.05 <= t <= c[-1][1] + 0.25:
                    cur = c
            if cur:
                draw_captions(d, cur, t)
            d.text((36, H - 62), lab["ai"], font=F_SEMI(24), fill=(200, 200, 210), stroke_width=2, stroke_fill=(0, 0, 0))
            d.rectangle([0, H - 12, int(W * t / total), H], fill=AMBER)
            return img

        ff = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
             "-r", str(FPS), "-i", "-", "-i", str(voice), "-i", str(fx), "-filter_complex",
             "[1:a]apad=pad_dur=2[v];[v][2:a]amix=inputs=2:normalize=0:duration=longest,"
             "loudnorm=I=-14:TP=-1.5[a]", "-map", "0:v", "-map", "[a]",
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
