"""Selbst erzeugte Soundeffekte und Hintergrundmusik (keine fremden Audiodateien, keine Lizenzfragen).

  ding   Aufzug-Gong beim Öffnen der Türen
  whoosh Luftzug bei jedem Bildwechsel
  pop    kurzer Plopp, wenn Zahl oder Urteil erscheint
  tick   Klick beim Hochzählen der Etagenanzeige
  music  spannungsgeladener Puls (Bass, Kick, Hi-Hat) als Bett unter der Stimme
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
    return 0.5 * out / np.abs(out).max()


def pop():
    t = _t(0.12)
    f = 900 * np.exp(-t * 25) + 220
    ph = 2 * np.pi * np.cumsum(f) / SR
    return 0.45 * np.sin(ph) * np.exp(-t * 30)


def tick():
    t = _t(0.03)
    return 0.25 * np.sin(2 * np.pi * 2200 * t) * np.exp(-t * 180)


def music(sec, bpm=104, seed=3):
    """Leiser, treibender Puls in a-Moll."""
    rng = np.random.default_rng(seed)
    n = int(SR * sec)
    out = np.zeros(n)
    beat = 60 / bpm
    kick_t = _t(0.25)
    kick = np.sin(2 * np.pi * np.cumsum(50 + 90 * np.exp(-kick_t * 30)) / SR) * np.exp(-kick_t * 12)
    hat_t = _t(0.05)
    hat = rng.standard_normal(len(hat_t)) * np.exp(-hat_t * 90)
    hat = np.diff(hat, prepend=0)  # Hochpass
    bass_notes = [55.0, 55.0, 43.65, 49.0]  # A, A, F, G
    k = 0
    while k * beat < sec:
        i = int(k * beat * SR)
        seg = kick[: max(0, min(len(kick), n - i))]
        out[i:i + len(seg)] += 0.9 * seg
        j = int((k + 0.5) * beat * SR)
        seg = hat[: max(0, min(len(hat), n - j))]
        out[j:j + len(seg)] += 0.25 * seg
        if k % 4 == 0:  # neuer Basston pro Takt
            f = bass_notes[(k // 4) % len(bass_notes)]
            ln = min(int(4 * beat * SR), n - i)
            tt = np.arange(ln) / SR
            saw = 2 * ((f * tt) % 1) - 1
            sm = np.convolve(saw, np.ones(40) / 40, mode="same")
            out[i:i + ln] += 0.35 * sm * np.minimum(1, tt * 20) * np.exp(-tt * 0.4)
        k += 1
    fade = np.minimum(1, np.minimum(np.arange(n) / (SR * 1.0), (n - np.arange(n)) / (SR * 1.5)))
    return 0.5 * out * fade / max(np.abs(out).max(), 1e-6)


def mix(events, sec, music_gain=0.10):
    """events: [(zeit_s, name)] -> Stereo-Spur als numpy-Array."""
    bank = {"ding": ding(), "whoosh": whoosh(), "pop": pop(), "tick": tick()}
    out = music(sec) * music_gain if music_gain else np.zeros(int(SR * sec))
    for at, name in events:
        s = bank[name]
        i = int(at * SR)
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
