"""Version 4: orientiert am Aufbau erfolgreicher „8 Level“-Reels (Vorbild-Analyse _8_levels), mit eigener Note.

Aufbau eines Teils:
  Aufzug-Intro (eigenes Markenzeichen, 1 s) -> Szene mit Werte-Leiste oben (3 Kennzahlen mit Balken),
  schnelle Bildwechsel, Untertitel in schmaler Großschrift mit markiertem Schlüsselwort -> Zitat-Karte
  auf dunklem Grund, wenn jemand etwas Schlüsselhaftes sagt -> Rangliste „DIE 8 LEVEL VON …“ mit „???“
  und „LEVEL n+1 → NEXT“, dazu der feste Satz „Das siehst du in Level X.“
"""
import difflib
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import sfx, tts
from .render import FONTS, FPS, H, LABELS, W, chunk_words
from .render_lift import (CUT, DOOR_OPEN, SAFE_CX, SAFE_W, cover, draw_doors, ease, fit_font, make_doors,
                          pop_scale, sentence_starts, shot)

ACCENT = (255, 184, 28)      # unsere Akzentfarbe (Bernstein), Vorbild nutzt Koralle
ACCENT_DARK = (120, 80, 0)
INK = (22, 18, 16)
CREAM = (245, 236, 220)
F_COND = lambda s: ImageFont.truetype(str(FONTS / "Anton-Regular.ttf"), s)
F_MONO = lambda s: ImageFont.truetype(str(FONTS / "JetBrainsMono-Bold.ttf"), s)
BAR_COLORS = [(110, 200, 120), (255, 184, 28), (90, 160, 255)]
V4_LABELS = {
    "de": {"next": "FOLGT", "levels": "DIE 8 LEVEL VON", "said": "ER SAGTE", "quote": "ZITAT",
           "you": "WELCHE ZAHL STÜNDE AUF DEINER STIRN?"},
    "en": {"next": "NEXT", "levels": "THE 8 LEVELS OF", "said": "HE SAID", "quote": "QUOTE",
           "you": "WHAT NUMBER WOULD BE ON YOUR FOREHEAD?"},
}


COUNT_UP = 1.0


def count_text(val, frac):
    """Zahl im Text hochzählen lassen: "1.150 €" bei frac 0.5 -> "575 €"."""
    m = re.search(r"\d[\d.,]*", val)
    if not m or frac >= 1:
        return val
    raw = m.group(0)
    sep = "." if "." in raw and "," not in raw[-3:] else ","
    digits = re.sub(r"[.,]\d{1,2}$", "", raw) if re.search(r"[.,]\d{1,2}$", raw) else raw
    try:
        num = int(re.sub(r"\D", "", digits))
    except ValueError:
        return val
    cur = f"{int(num * ease(frac)):,}".replace(",", sep)
    return val[:m.start()] + cur + val[m.end():]


def draw_hud(img, stats, t_in, first=None):
    """Drei Kennzahl-Kästen oben, fahren ein, die Zahlen zählen hoch. first ersetzt den ersten Wert (Wendung)."""
    if not stats:
        return
    d = ImageDraw.Draw(img, "RGBA")
    k = len(stats[:3])
    gap, x0, y = 18, 60, 120 - int(60 * (1 - ease(t_in / 0.3)))
    bw = (SAFE_W - gap * (k - 1)) / k
    for i, st in enumerate(stats[:3]):
        x = x0 + i * (bw + gap)
        d.rounded_rectangle([x, y, x + bw, y + 120], radius=14, fill=(18, 16, 14, 215), outline=(255, 255, 255, 40), width=2)
        d.text((x + 16, y + 12), str(st.get("label", "")).upper()[:14], font=F_MONO(20), fill=(200, 195, 185))
        val = str(first if (i == 0 and first) else st.get("value", ""))
        val = count_text(val, t_in / COUNT_UP) if not (i == 0 and first) else val
        d.text((x + 16, y + 38), val, font=fit_font(d, val, F_COND, 50, bw - 30, 26), fill=(255, 255, 255))
        frac = max(0.02, min(1.0, float(st.get("bar", 0.5) or 0)))
        d.rounded_rectangle([x + 16, y + 100, x + bw - 16, y + 108], radius=4, fill=(255, 255, 255, 40))
        d.rounded_rectangle([x + 16, y + 100, x + 16 + (bw - 32) * frac, y + 108], radius=4,
                            fill=BAR_COLORS[i % 3] + (255,))


INTRO = 1.1


def draw_intro(img, txt, t):
    """Statt Aufzugtüren: Rolle bzw. Betrag der Figur knallt ins Bild und fliegt dann nach oben links weg."""
    d = ImageDraw.Draw(img, "RGBA")
    k = ease(min(t / 0.15, 1))
    out = ease(max(t - 0.75, 0) / 0.35)
    size = int(230 * (0.5 + 0.6 * k - 0.1 * min(t / 0.3, 1)) * (1 - 0.7 * out))
    f = F_COND(max(size, 20))
    f = fit_font(d, txt, F_COND, max(size, 20), SAFE_W - 80, 20)
    w = d.textlength(txt, font=f)
    x = SAFE_CX - w / 2 - out * (SAFE_CX - 160)
    y = 760 - out * 700
    pad = 30 * (1 - out)
    d.rounded_rectangle([x - pad, y - pad / 2, x + w + pad, y + size * 1.15 + pad / 2], radius=30, fill=ACCENT + (235,))
    d.text((x, y), txt, font=f, fill=INK)


def draw_delta(img, delta, t):
    """Großes "+500 €" / "-400 €" springt auf und fliegt zur Werte-Leiste: die Zahl ändert sich live."""
    d = ImageDraw.Draw(img, "RGBA")
    neg = delta.strip().startswith(("-", "−"))
    col = (235, 70, 70) if neg else (70, 210, 110)
    sc = 0.6 + 0.5 * ease(min(t / 0.18, 1)) - 0.1 * ease(min(max(t - 0.18, 0) / 0.2, 1))
    f = F_COND(int(170 * sc))
    w = d.textlength(delta, font=f)
    y = 620 - int(380 * ease(max(t - 1.0, 0) / 0.6))
    alpha = 255 if t < 1.2 else int(255 * max(0, 1 - (t - 1.2) / 0.4))
    d.text((SAFE_CX - w / 2, y), delta, font=f, fill=col + (alpha,), stroke_width=10, stroke_fill=(0, 0, 0, alpha))


def draw_captions_v4(d, chunk, t, y=1470):
    words = [w[2].upper() for w in chunk]
    fnt = fit_font(d, " ".join(words), F_COND, 96, SAFE_W - 20, 50)
    space = d.textlength(" ", font=fnt)
    widths = [d.textlength(w, font=fnt) for w in words]
    x = SAFE_CX - (sum(widths) + space * (len(words) - 1)) / 2
    for (a, b, _), w, ww in zip(chunk, words, widths):
        if a <= t < b + 0.05:  # aktives Wort: farbiger Kasten dahinter
            bx = d.textbbox((x, y), w, font=fnt)
            d.rounded_rectangle([bx[0] - 12, bx[1] - 10, bx[2] + 12, bx[3] + 10], radius=10, fill=ACCENT)
            d.text((x, y), w, font=fnt, fill=INK)
        else:
            d.text((x, y), w, font=fnt, fill=(255, 255, 255), stroke_width=8, stroke_fill=(0, 0, 0))
        x += ww + space


def quote_card(text, label):
    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)
    f = F_COND(110)
    lines, cur = [], ""
    for w in f"„{text.strip(' „“\"')}“".split():
        test = (cur + " " + w).strip()
        if d.textlength(test, font=f) <= SAFE_W:
            cur = test
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    lh = int(f.size * 1.15)
    y0 = int(H * 0.42 - len(lines) * lh / 2)
    lw = d.textlength(label, font=F_MONO(26))
    d.text((SAFE_CX - lw / 2, y0 - 70), label, font=F_MONO(26), fill=(170, 160, 150))
    for i, ln in enumerate(lines):
        tw = d.textlength(ln, font=f)
        d.text((SAFE_CX - tw / 2, y0 + i * lh), ln, font=f, fill=ACCENT)
    return img


def leaderboard(series, n, lab, reveal):
    """Rangliste wie beim Vorbild: Level 8 oben, nur bisher gezeigte Level sind aufgedeckt."""
    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)
    topic = series["title"].split("...")[-1]
    head = lab["levels"]
    hw = d.textlength(head, font=F_MONO(28))
    d.text((SAFE_CX - hw / 2, 330), head, font=F_MONO(28), fill=(170, 160, 150))
    sub = re.sub(r"^(Die|The)\s+8\s+Level[s]?\s+(von|of)\s+", "", series["title"], flags=re.I).upper()
    fs = fit_font(d, sub, F_COND, 84, SAFE_W)
    sw = d.textlength(sub, font=fs)
    d.text((SAFE_CX - sw / 2, 375), sub, font=fs, fill=(255, 255, 255))
    y0, row = 520, 105
    for i, k in enumerate(range(8, 0, -1)):
        y = y0 + i * row
        shown = k <= n
        col = ACCENT if k == n else ((235, 228, 215) if shown else (110, 104, 98))
        d.line([(60, y + row - 8), (940, y + row - 8)], fill=(50, 45, 42), width=2)
        d.text((60, y + 22), f"LEVEL {k}", font=F_MONO(30), fill=col)
        lv = series["levels"][k - 1]
        name = lv["name"].split(",")[0].upper() if shown else "???"
        d.text((300, y + 8), name, font=F_COND(58), fill=col)
        val = lv["badge"] if shown else "?"
        vf = fit_font(d, val, F_COND, 48, 260, 26)
        vw = d.textlength(val, font=vf)
        d.text((940 - vw, y + 16), val, font=vf, fill=col)
    if n < 8:
        pill = f"LEVEL {n + 1} → {lab['next']}"
        pf = F_COND(56)
        pw = d.textlength(pill, font=pf)
        s = 0.92 + 0.08 * abs(((reveal * 2) % 2) - 1)  # leichtes Pulsieren
        x0, y = SAFE_CX - pw / 2 - 40, y0 + 8 * row + 50
        d.rounded_rectangle([x0, y, x0 + (pw + 80) * s, y + 100 * s], radius=50, fill=ACCENT)
        d.text((x0 + 40 * s, y + 10 * s), pill, font=F_COND(int(56 * s)), fill=INK)
    if lab.get("you"):
        q = lab["you"] + " ↓"
        qf = fit_font(d, q, F_COND, 54, SAFE_W, 30)
        qw = d.textlength(q, font=qf)
        d.text((SAFE_CX - qw / 2, 1530), q, font=qf, fill=(255, 255, 255))
    return img


def _portrait(pic, size, dark=False):
    """Runder Ausschnitt aus dem oberen Bilddrittel (dort sitzt meist der Kopf mit der Stirn-Zahl)."""
    w, h = pic.size
    side = int(w * 0.8)
    crop = pic.crop(((w - side) // 2, int(h * 0.12), (w + side) // 2, int(h * 0.12) + side)).resize((size, size))
    if dark:
        crop = Image.blend(crop.filter(ImageFilter.GaussianBlur(14)), Image.new("RGB", (size, size), (10, 10, 14)), 0.82)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    return crop, mask


def endcard(series, n, lab, t, pic):
    """Abspann: verschwommene Szene, große Karte der aktuellen Figur, gesperrte Karte des nächsten Levels."""
    lv = series["levels"][n - 1]
    bg = pic.resize((W // 8, H // 8)).filter(ImageFilter.GaussianBlur(3)).resize((W, H))
    img = Image.blend(bg, Image.new("RGB", (W, H), (12, 10, 14)), 0.55)
    d = ImageDraw.Draw(img, "RGBA")
    sub = re.sub(r"^(Die|The)\s+8\s+Level[s]?\s+(von|of)\s+", "", series["title"], flags=re.I).upper()
    head = lab["levels"]
    hw = d.textlength(head, font=F_MONO(28))
    d.text((SAFE_CX - hw / 2, 170), head, font=F_MONO(28), fill=(235, 228, 215))
    fs = fit_font(d, sub, F_COND, 96, SAFE_W)
    sw = d.textlength(sub, font=fs)
    d.text((SAFE_CX - sw / 2, 215), sub, font=fs, fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
    # aktuelle Figur
    pop = ease(min(t / 0.35, 1))
    size = int(380 * (0.85 + 0.15 * pop))
    por, mask = _portrait(pic, size)
    cx, cy = SAFE_CX, 560
    d.ellipse([cx - size / 2 - 12, cy - 12, cx + size / 2 + 12, cy + size + 12], fill=ACCENT + (255,))
    img.paste(por, (int(cx - size / 2), cy), mask)
    d = ImageDraw.Draw(img, "RGBA")
    name = lv["name"].split(",")[0].upper()
    for txt, f, col, y in ((name, F_COND(84), (255, 255, 255), cy + size + 30),
                           (str(lv["badge"]), F_COND(70), ACCENT, cy + size + 130)):
        f = fit_font(d, txt, lambda z: F_COND(z), f.size, SAFE_W - 40, 30)
        tw = d.textlength(txt, font=f)
        d.text((SAFE_CX - tw / 2, y), txt, font=f, fill=col, stroke_width=5, stroke_fill=(0, 0, 0))
    if n < 8:
        # gesperrte Karte: nächstes Level als dunkle Silhouette mit Fragezeichen
        y0 = 1300
        d.rounded_rectangle([110, y0, 890, y0 + 190], radius=40, fill=(20, 18, 24, 230), outline=ACCENT + (255,), width=4)
        sil, smask = _portrait(pic, 150, dark=True)
        img.paste(sil, (140, y0 + 20), smask)
        d = ImageDraw.Draw(img, "RGBA")
        d.text((190, y0 + 40), "?", font=F_COND(90), fill=ACCENT)
        pulse = 0.85 + 0.15 * abs(((t * 2) % 2) - 1)
        nxt = f"LEVEL {n + 1}"
        d.text((320, y0 + 28), nxt, font=F_COND(int(72 * pulse)), fill=(255, 255, 255))
        d.text((320, y0 + 120), lab["next"], font=F_MONO(34), fill=ACCENT)
    if lab.get("you"):
        q = lab["you"]
        qf = fit_font(d, q, F_COND, 54, SAFE_W, 30)
        qw = d.textlength(q, font=qf)
        d.text((SAFE_CX - qw / 2, 1540), q, font=qf, fill=(255, 255, 255), stroke_width=5, stroke_fill=(0, 0, 0))
    return img


def find_quote(words, quote):
    """Zeitbereich, in dem das Zitat gesprochen wird (oder None)."""
    if not quote:
        return None
    norm = lambda w: re.sub(r"[^\w]", "", w.lower())
    q = [norm(w) for w in quote.split() if norm(w)]
    ws = [norm(w[2]) for w in words]
    sm = difflib.SequenceMatcher(None, ws, q, autojunk=False)
    m = max(sm.get_matching_blocks(), key=lambda b: b.size)
    if m.size < max(2, len(q) // 2):
        return None
    a = words[m.a][0]
    b = words[min(m.a + len(q) - 1, len(words) - 1)][1]
    return (a - 0.1, b + 0.5)


def render_part(series, n, images, out_path, backend="gemini"):
    lang = series["lang"]
    lv = series["levels"][n - 1]
    lab = LABELS[lang]
    vl = V4_LABELS.get(lang, V4_LABELS["en"])
    pics = [cover(Image.open(p).convert("RGB"), W, H) for p in images]

    with tempfile.TemporaryDirectory() as tmp:
        voice = Path(tmp) / "voice.mp3"
        fig = {"w": "Kore", "m": "Puck"}.get(str(lv.get("gender", "m"))[:1].lower(), "Puck")
        cast = None
        if len({x["s"] for x in lv.get("lines", [])}) > 1:
            cast = {"lines": [(x["s"], x["t"]) for x in lv["lines"]], "voices": {"Erzaehler": "Charon", "Figur": fig},
                    "genders": [x.get("g") for x in lv["lines"]], "names": [x.get("n") for x in lv["lines"]]}
        dur, words = tts.speak(lv["story"], lang, voice, backend=backend, cast=cast)
        starts = sentence_starts(words)
        outro = words[starts[-1]][0] - 0.2 if len(starts) > 1 else dur - 2.5
        outro = min(max(outro, 8.0), dur - 1.5)
        total = dur + 1.6
        chunks = chunk_words(words)
        qspan = find_quote(words, lv.get("quote"))
        shots = lv.get("line_shots")  # ein Bild pro Skriptzeile, synchron zur Stimme
        qpic = None
        if qspan and lv.get("quote_image") and Path(lv["quote_image"]).exists():
            qpic = cover(Image.open(lv["quote_image"]).convert("RGB"), W, H)
        qcard = quote_card(lv["quote"], vl["quote"]) if (qspan and qpic is None and not shots) else None
        qby = lv.get("quote_by") or {}
        role = (lv["name"].split(",")[-1].strip() if "," in lv["name"] else lv["name"]).upper()
        hud_at = INTRO

        cuts, t = [], 0.0
        shot_of = []
        if shots:
            i = 0
            for k, x in enumerate(lv["lines"]):
                at = 0.0 if k == 0 else words[min(i, len(words) - 1)][0] - 0.08
                if at < outro or k == 0:
                    cuts.append(max(at, 0.0))
                    shot_of.append(shots[k])
                i += len(x["t"].split())
        else:
            while t < outro:
                cuts.append(t)
                shot_of.append(len(cuts) - 1)
                t += CUT
        events = [(0.05, "pop"), (hud_at, "pop")]
        events += [(hud_at + i * 0.08, "tick") for i in range(int(COUNT_UP / 0.08))]
        twist = lv.get("twist") or {}
        twist_at = qspan[1] if (qspan and twist.get("delta")) else None
        if shots and twist.get("delta") and lv.get("twist_line") is not None:
            upto = sum(len(x["t"].split()) for x in lv["lines"][:lv["twist_line"] + 1])
            twist_at = words[min(upto, len(words)) - 1][1] + 0.1
        if twist_at:
            events += [(twist_at, "pop")] + [(twist_at + 0.1 + i * 0.07, "tick") for i in range(8)]
        events += [(c, "whoosh") for c in cuts[3::3]]  # nur jeder 3. Schnitt, sonst nervt es
        if qspan:
            events.append((qspan[0], "pop"))
        events += [(outro, "whoosh"), (outro + 0.4, "pop"), (total - 0.9, "ding")]
        fx = Path(tmp) / "fx.wav"
        sfx.write_wav(fx, sfx.mix(events, total))
        mus = Path(tmp) / "music.wav"
        sfx.write_wav(mus, sfx.music(total, hits=[h for h in (twist_at, outro) if h]))

        def frame(t):
            if t >= outro:
                img = endcard(series, n, vl, t - outro, pics[0])
            elif qspan and qspan[0] <= t < qspan[1] and qpic is not None and not shots:
                # Die Person aus einem anderen Level ist zu sehen und sagt den Satz selbst
                img = shot(qpic, 7, (t - qspan[0]) / max(qspan[1] - qspan[0], 0.1))
                tag = f"{qby.get('name', '')} · {qby.get('badge', '')}".strip(" ·").upper()
                if tag:
                    dq = ImageDraw.Draw(img)
                    tf = fit_font(dq, tag, F_COND, 54, SAFE_W - 40, 30)
                    tw = dq.textlength(tag, font=tf)
                    dq.rounded_rectangle([SAFE_CX - tw / 2 - 24, 1300, SAFE_CX + tw / 2 + 24, 1300 + tf.size * 1.3],
                                         radius=20, fill=(235, 70, 70))
                    dq.text((SAFE_CX - tw / 2, 1300 + tf.size * 0.1), tag, font=tf, fill=(255, 255, 255))
            elif qspan and qspan[0] <= t < qspan[1] and qcard is not None:
                img = qcard.copy()
            else:
                k = max([i for i, c in enumerate(cuts) if c <= t] or [0])
                c0 = cuts[k] if t >= cuts[0] else 0
                c1 = cuts[k + 1] if k + 1 < len(cuts) else outro
                img = shot(pics[shot_of[k] % len(pics)], k, (t - c0) / max(c1 - c0, 0.1))
                if k > 0 and t - c0 < 0.07:
                    img = Image.blend(img, Image.new("RGB", (W, H), (255, 255, 255)), 0.3 * (1 - (t - c0) / 0.07))
                if t < INTRO:
                    draw_intro(img, role, t)
                if t >= hud_at:
                    after = twist.get("after") if (twist_at and t >= twist_at) else None
                    draw_hud(img, lv.get("stats"), t - hud_at, after)
                if twist_at and twist_at <= t < twist_at + 1.6:
                    draw_delta(img, twist["delta"], t - twist_at)
            d = ImageDraw.Draw(img)
            # Marke oben links: Betrag der Figur statt „Level“ (Wunsch João)
            pill = str(twist.get("after") if (twist_at and t >= twist_at) else (lv.get("badge") or role)).upper()
            pf = fit_font(d, pill, F_COND, 40, 420, 24)
            pw = d.textlength(pill, font=pf)
            d.rounded_rectangle([60, 40, 60 + pw + 48, 92], radius=26, fill=ACCENT)
            d.text((84, 42), pill, font=pf, fill=INK)
            cur = None
            for c in chunks:
                if c[0][0] - 0.05 <= t <= c[-1][1] + 0.25:
                    cur = c
            in_quote = qspan and qspan[0] <= t < qspan[1] and qcard is not None
            if cur and not in_quote and t < outro:
                draw_captions_v4(d, cur, t)
            d.text((36, H - 62), lab["ai"], font=F_MONO(20), fill=(200, 200, 210))
            d.rectangle([0, H - 10, int(W * t / total), H], fill=ACCENT)
            return img

        ff = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
             "-r", str(FPS), "-i", "-", "-i", str(voice), "-i", str(fx), "-i", str(mus), "-filter_complex",
             # Musik taucht unter der Stimme ab (Sidechain) und kommt in Pausen und im Outro hoch
             "[1:a]apad=pad_dur=2,asplit=2[v][vk];[3:a]volume=0.55[m0];"
             "[m0][vk]sidechaincompress=threshold=0.02:ratio=5:attack=15:release=350[m];"
             "[v][2:a][m]amix=inputs=3:normalize=0:duration=longest,"
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
