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

from PIL import Image, ImageDraw, ImageFont

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
    "de": {"next": "FOLGT", "levels": "DIE 8 LEVEL VON", "said": "ER SAGTE", "quote": "ZITAT"},
    "en": {"next": "NEXT", "levels": "THE 8 LEVELS OF", "said": "HE SAID", "quote": "QUOTE"},
}


def draw_hud(img, stats, t_in):
    """Drei Kennzahl-Kästen oben, fahren beim ersten Auftauchen kurz ein."""
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
        val = str(st.get("value", ""))
        d.text((x + 16, y + 38), val, font=fit_font(d, val, F_COND, 50, bw - 30, 26), fill=(255, 255, 255))
        frac = max(0.02, min(1.0, float(st.get("bar", 0.5) or 0)))
        d.rounded_rectangle([x + 16, y + 100, x + bw - 16, y + 108], radius=4, fill=(255, 255, 255, 40))
        d.rounded_rectangle([x + 16, y + 100, x + 16 + (bw - 32) * frac, y + 108], radius=4,
                            fill=BAR_COLORS[i % 3] + (255,))


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
    doors = make_doors(str(n))

    with tempfile.TemporaryDirectory() as tmp:
        voice = Path(tmp) / "voice.mp3"
        fig = {"w": "Kore", "m": "Puck"}.get(str(lv.get("gender", "m"))[:1].lower(), "Puck")
        cast = None
        if len({x["s"] for x in lv.get("lines", [])}) > 1:
            cast = {"lines": [(x["s"], x["t"]) for x in lv["lines"]], "voices": {"Erzaehler": "Charon", "Figur": fig}}
        dur, words = tts.speak(lv["story"], lang, voice, backend=backend, cast=cast)
        starts = sentence_starts(words)
        outro = words[starts[-1]][0] - 0.2 if len(starts) > 1 else dur - 2.5
        outro = min(max(outro, 8.0), dur - 1.5)
        total = dur + 1.6
        chunks = chunk_words(words)
        qspan = find_quote(words, lv.get("quote"))
        qcard = quote_card(lv["quote"], vl["quote"]) if qspan else None
        hud_at = DOOR_OPEN[1]

        cuts, t = [], DOOR_OPEN[0]
        while t < outro:
            cuts.append(t)
            t += CUT
        events = [(0.1, "tick"), (DOOR_OPEN[0] - 0.1, "ding"), (hud_at, "pop")]
        events += [(c, "whoosh") for c in cuts[1:]]
        if qspan:
            events.append((qspan[0], "pop"))
        events += [(outro, "whoosh"), (outro + 0.4, "pop"), (total - 0.9, "ding")]
        fx = Path(tmp) / "fx.wav"
        sfx.write_wav(fx, sfx.mix(events, total))

        def frame(t):
            if t >= outro:
                img = leaderboard(series, n, vl, t - outro)
            elif qspan and qspan[0] <= t < qspan[1]:
                img = qcard.copy()
            else:
                k = max([i for i, c in enumerate(cuts) if c <= t] or [0])
                c0 = cuts[k] if t >= cuts[0] else 0
                c1 = cuts[k + 1] if k + 1 < len(cuts) else outro
                img = shot(pics[k % len(pics)], k, (t - c0) / max(c1 - c0, 0.1))
                if k > 0 and t - c0 < 0.07:
                    img = Image.blend(img, Image.new("RGB", (W, H), (255, 255, 255)), 0.3 * (1 - (t - c0) / 0.07))
                if t < DOOR_OPEN[1]:
                    draw_doors(img, doors, (t - DOOR_OPEN[0]) / (DOOR_OPEN[1] - DOOR_OPEN[0]))
                if t >= hud_at:
                    draw_hud(img, lv.get("stats"), t - hud_at)
            d = ImageDraw.Draw(img)
            # Level-Marke oben links (klein, dezent)
            d.rounded_rectangle([60, 40, 250, 92], radius=26, fill=ACCENT)
            d.text((84, 42), f"LEVEL {n}/8", font=F_COND(40), fill=INK)
            cur = None
            for c in chunks:
                if c[0][0] - 0.05 <= t <= c[-1][1] + 0.25:
                    cur = c
            in_quote = qspan and qspan[0] <= t < qspan[1]
            if cur and not in_quote and not (t >= outro + 0.3):
                draw_captions_v4(d, cur, t)
            d.text((36, H - 62), lab["ai"], font=F_MONO(20), fill=(200, 200, 210))
            d.rectangle([0, H - 10, int(W * t / total), H], fill=ACCENT)
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
