"""Selbst erzeugte Soundeffekte und Hintergrundmusik (keine fremden Audiodateien, keine Lizenzfragen).

  ding   Aufzug-Gong beim Öffnen der Türen
  whoosh Luftzug bei jedem Bildwechsel
  pop    kurzer Plopp, wenn Zahl oder Urteil erscheint
  tick   Klick beim Hochzählen der Etagenanzeige
  music  cinematische Drama-Musik (Streicher, Klavier, Herzschlag, Riser + Boom auf dem Twist)
"""
import wave

import numpy as np

SR = 44100


def _t(sec):
    return np.arange(int(SR * sec)) / SR


def ding():
    t = _t(1.6)
    out = np.zeros_like(t)
    for start, f in ((0.0, 1318.5), (0.28, 1046.5)):
        tt = np.clip(t - start, 0, None)
        env = np.where(t >= start, np.exp(-tt * 3.2), 0)
        out += env * (np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(2 * np.pi * 2 * f * tt)
                      + 0.12 * np.sin(2 * np.pi * 3.01 * f * tt))
    return 0.35 * out / np.abs(out).max()


def whoosh(sec=0.45, seed=1):
    rng = np.random.default_rng(seed)
    n = int(SR * sec)
    noise = rng.standard_normal(n)
    # Tiefpass mit wanderndem Glättungsfenster = Rauschen, das an- und abschwillt
    out = np.zeros(n)
    acc = 0.0
    for i in range(n):
        a = 0.02 + 0.25 * np.sin(np.pi * i / n) ** 2
        acc += a * (noise[i] - acc)
        out[i] = acc
    env = np.sin(np.pi * np.linspace(0, 1, n)) ** 1.5
    out *= env
    return 0.15 * out / np.abs(out).max()  # leise: João fand ihn zu laut


def pop():
    t = _t(0.12)
    f = 900 * np.exp(-t * 25) + 220
    ph = 2 * np.pi * np.cumsum(f) / SR
    return 0.45 * np.sin(ph) * np.exp(-t * 30)


def tick():
    t = _t(0.03)
    return 0.25 * np.sin(2 * np.pi * 2200 * t) * np.exp(-t * 180)


def _note(f):
    return 440.0 * 2 ** ((f - 69) / 12)


def _pad(freqs, ln, seed):
    """Weiche Streicherfläche: mehrere leicht verstimmte Sägezähne, stark geglättet."""
    rng = np.random.default_rng(seed)
    tt = np.arange(ln) / SR
    out = np.zeros(ln)
    for f in freqs:
        for det in (-0.12, 0.0, 0.11):
            ph = rng.random()
            out += 2 * ((f * (1 + det / 100) * tt + ph) % 1) - 1
    k = 90
    out = np.convolve(out, np.ones(k) / k, mode="same")
    out = np.convolve(out, np.ones(k) / k, mode="same")
    att = np.minimum(1, tt / 0.6)
    rel = np.minimum(1, (ln / SR - tt) / 0.5)
    return out * att * np.clip(rel, 0, 1) * (1 + 0.15 * np.sin(2 * np.pi * 0.25 * tt))


def _pluck(f, sec=1.2):
    """Klavierähnlicher Anschlag."""
    t = _t(sec)
    env = np.exp(-t * 4.5)
    return env * (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 3)
                  + 0.15 * np.sin(2 * np.pi * 3 * f * t) * np.exp(-t * 6))


def _boom():
    t = _t(1.8)
    f = 38 + 60 * np.exp(-t * 8)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 2.2)
    rng = np.random.default_rng(7)
    crack = rng.standard_normal(len(t)) * np.exp(-t * 25)
    return body + 0.3 * np.convolve(crack, np.ones(8) / 8, mode="same")


def _riser(sec=1.6):
    rng = np.random.default_rng(5)
    n = int(SR * sec)
    noise = np.diff(rng.standard_normal(n), prepend=0)
    t = np.arange(n) / SR
    tone = np.sin(2 * np.pi * np.cumsum(200 + 900 * (t / sec) ** 2) / SR)
    noise = np.convolve(noise, np.ones(6) / 6, mode="same")  # weniger zischelig
    return (0.4 * noise + 0.4 * tone) * (t / sec) ** 2.5


# Akkordfolge d-Moll: Dm – Bb – F – C (i–VI–III–VII), wie in den Vorbild-Dramen (Analyse musik/MUSIK.md)
CHORDS = [(62, 65, 69), (58, 62, 65), (53, 60, 65), (60, 64, 67)]


def music(sec, bpm=72, hits=(), seed=3):
    """Cinematische Spannungsmusik: Streicherfläche, Klavier-Arpeggio, Herzschlag-Bass.
    Ab der Hälfte setzt der Beat voll ein; hits = Zeitpunkte (Twist, Outro) mit Riser davor und Boom darauf."""
    rng = np.random.default_rng(seed)
    n = int(SR * sec)
    out = np.zeros(n)
    beat = 60 / bpm
    bar = 4 * beat
    kick_t = _t(0.3)
    kick = np.sin(2 * np.pi * np.cumsum(45 + 80 * np.exp(-kick_t * 28)) / SR) * np.exp(-kick_t * 10)
    hat_t = _t(0.04)
    hat = np.diff(rng.standard_normal(len(hat_t)) * np.exp(-hat_t * 110), prepend=0)

    def put(sig, at, gain):
        i = int(at * SR)
        if i >= n or i + len(sig) <= 0:
            return
        if i < 0:
            sig, i = sig[-i:], 0
        seg = sig[: n - i]
        out[i:i + len(seg)] += gain * seg

    b = 0
    while b * bar < sec:
        t0 = b * bar
        chord = CHORDS[b % len(CHORDS)]
        ln = int(min(bar + 0.4, sec - t0) * SR)
        if ln > SR * 0.1:
            put(_pad([_note(m - 12) for m in chord], ln, seed + b), t0, 0.10)
        full = t0 >= sec * 0.35
        arp = [chord[0], chord[1], chord[2], chord[1] + 12 if full else chord[1]]
        for k in range(8 if full else 4):  # Achtel bzw. Viertel
            step = beat / 2 if full else beat
            put(_pluck(_note(arp[k % 4] + 12)), t0 + k * step, 0.22)
        for k in range(4):
            # Herzschlag: zwei Schläge kurz hintereinander, später durchgehender Beat
            put(kick, t0 + k * beat, 0.7 if full else (0.5 if k % 2 == 0 else 0))
            if not full and k % 2 == 0:
                put(kick, t0 + k * beat + 0.18, 0.3)
            if full:
                put(hat, t0 + (k + 0.5) * beat, 0.1)
        bass_ln = int(min(bar, sec - t0) * SR)
        if bass_ln > 0:
            tt = np.arange(bass_ln) / SR
            put(np.sin(2 * np.pi * _note(chord[0] - 24) * tt) * np.minimum(1, tt * 10) * np.exp(-tt * 0.5), t0, 0.35)
        b += 1
    for h in hits:
        put(_riser(), h - 1.6, 0.15)
        put(_boom(), h, 0.6)
    fade = np.minimum(1, np.minimum(np.arange(n) / (SR * 0.8), (n - np.arange(n)) / (SR * 1.5)))
    return 0.6 * out * fade / max(np.abs(out).max(), 1e-6)


def mix(events, sec, music_gain=0.0):
    """events: [(zeit_s, name)] -> Effektspur (Musik kommt getrennt, damit sie unter der Stimme abtauchen kann)."""
    bank = {"ding": ding(), "whoosh": whoosh(), "pop": pop(), "tick": tick()}
    out = music(sec) * music_gain if music_gain else np.zeros(int(SR * sec))
    for at, name in events:
        s = bank[name]
        i = max(0, int(at * SR))
        if i >= len(out):
            continue
        seg = s[: len(out) - i]
        out[i:i + len(seg)] += seg
    return np.clip(out, -1, 1)


def write_wav(path, samples):
    data = (samples * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
