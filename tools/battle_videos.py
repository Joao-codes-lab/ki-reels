"""Videos direkt aus den Battle-Royale-Finalisten rendern: ein Bild pro Skriptzeile, jede Figur mit eigener Stimme.

  python tools/battle_videos.py data/battle/finalisten_runde1.json --extra data/battle/finalisten_level2-3.json \
      --plan "B2:1-3,D1:1-3,B3:1,A10:1,D4:1" --out /tmp/research/battle

Level 1 kommt aus skript_teil1/figuren_teil1, spätere Level aus der Zusatzdatei
([{"id": "B2", "levels": [{"level": 2, "figuren": [...], "skript": [...]}]}]).
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_daily  # noqa: E402
from reels import imagegen, scriptgen  # noqa: E402

LOOK = ("Every character is a cartoon fruit or vegetable creature (no humans, no human faces) with a small glowing "
        "digital number on its forehead.")


def amounts(zahl):
    """'40 € → 0 €' -> ['40 €', '0 €']"""
    return [m.strip() for m in re.findall(r"[−-]?\d[\d.,]*\s*(?:€|\$|Euro)?", zahl or "")]


def to_int(a):
    a = re.sub(r"[^\d.,−-]", "", a).replace("−", "-")
    a = re.sub(r"[.,]\d{1,2}$", "", a).replace(".", "").replace(",", "")
    try:
        return int(a)
    except ValueError:
        return None


def find_fig(figs, sprecher):
    for f in figs:
        if sprecher in (f.get("kurz"), f["name"]) or sprecher in f["name"].split():
            return f
    return {"name": sprecher, "obst": "", "zahl": "", "look": "", "g": "m"}


def build_level(n, figs, skript, schluss=None):
    sp = Counter(s["sprecher"] for s in skript if not s["sprecher"].startswith("Erz"))
    ranked = [k for k, _ in sp.most_common()]
    main = ranked[0]
    anta = ranked[1] if len(ranked) > 1 else None
    mf = find_fig(figs, main)
    lines = []
    for s in skript:
        who = s["sprecher"]
        role = ("Erzaehler" if who.startswith("Erz") else "Figur" if who == main
                else "Gegenspieler" if who == anta else "Nebenfigur")
        lines.append({"s": role, "t": s["text"], "g": find_fig(figs, who).get("g", "m"), "n": who})
    am = amounts(mf.get("zahl"))
    badge = am[0] if am else (mf.get("zahl") or "?")[:12]
    lv = {"n": n, "name": mf["name"], "badge": badge, "gender": mf.get("g", "m"), "character": mf.get("look", ""),
          "lines": lines, "story": " ".join(x["t"] for x in lines), "line_shots": list(range(len(skript))),
          "visual": skript[0]["bild"], "caption": "", "stats": [{"label": "Stirnzahl", "value": badge},
                                                                {"label": "Level", "value": f"{n} / 8"}]}
    if len(am) > 1:  # Zahl auf der Stirn springt: Wendepunkt ist die Zeile, deren Effekt die neue Zahl nennt
        after = am[-1]
        eff = [(i, s.get("stirnzahl_effekt") or "") for i, s in enumerate(skript)]
        cand = [i for i, e in eff if after.split()[0] in e]
        both = [i for i in cand if am[0].split()[0] in eff[i][1]]  # Zeile, in der die Zahl von alt auf neu springt
        hit = (both or cand or [None])[-1]
        a, b = to_int(am[0]), to_int(after)
        if hit is not None and a is not None and b is not None:
            d = b - a
            lv["twist_line"] = hit
            lv["twist"] = {"delta": f"{'+' if d >= 0 else '−'}{abs(d):,} €".replace(",", "."), "after": after}
    return lv


def prompt_for(scene, figs):
    looks = []
    for f in figs:
        if any(w in scene for w in {f.get("kurz") or "", f["name"].split()[-1]} if w):
            looks.append(f"{f['name']}: {' '.join(f.get('look', '').split()[:22])}")
    p = f"{scene}. {' '.join(looks[:2])}. {LOOK}"
    return p[:880]


def to_english(prompts):
    """Bildbeschreibungen ins Englische (die Bild-KI versteht Englisch besser). Bei Fehler bleibt es Deutsch."""
    try:
        res = scriptgen.ask("Translate each image description to concise English, keep names and numbers. "
                            'Answer ONLY with JSON: {"en": [str, ...]} in the same order.\n'
                            + json.dumps(prompts, ensure_ascii=False))
        en = res.get("en") or []
        if len(en) == len(prompts):
            return en
    except Exception as e:
        print("Übersetzung fehlgeschlagen:", e)
    return prompts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--extra", default=None)
    ap.add_argument("--plan", default="B2:1-3,D1:1-3,B3:1,A10:1,D4:1")
    ap.add_argument("--lang", default="de")
    ap.add_argument("--frame", default="frucht")
    ap.add_argument("--out", default="/tmp/research/battle")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    fin = {x["id"]: x for src in a.src.split(",") for x in run_daily.load(Path(src), [])}
    extra = {}
    for ex in (a.extra or "").split(","):
        if not ex or not Path(ex).exists():
            continue
        for x in run_daily.load(Path(ex), []):
            for lv in x.get("levels", []):
                extra[(x["id"], int(lv["level"]))] = lv
    style = scriptgen.FRAMES.get(a.frame, {}).get("style") or imagegen.STYLE
    backend = "eleven" if os.environ.get("ELEVENLABS_API_KEY") else "gemini"
    for item in a.plan.split(","):
        sid, rng = item.split(":")
        lo, _, hi = rng.partition("-")
        x = fin.get(sid)
        if not x:
            print(f"{sid}: nicht gefunden")
            continue
        title = x["titel_de"] if a.lang == "de" else x["titel_en"]
        levels = []
        for k, arc in enumerate(x.get("bogen_kurz", [])[:8], 1):  # Platzhalter für die gesperrten Level im Endbild
            m = re.match(r"Level \d+:\s*([^–-]+)", arc)
            levels.append({"n": k, "name": (m.group(1).strip() if m else f"Level {k}"), "badge": "?"})
        while len(levels) < 8:
            levels.append({"n": len(levels) + 1, "name": "???", "badge": "?"})
        series = {"lang": a.lang, "title": title, "house": "", "catchphrase": x.get("catchphrase_de"), "levels": levels}
        for n in range(int(lo), int(hi or lo) + 1):
            if n == 1:
                figs, skript = x["figuren_teil1"], x["skript_teil1"]
            elif (sid, n) in extra:
                figs, skript = extra[(sid, n)].get("figuren", []), extra[(sid, n)]["skript"]
            else:
                print(f"{sid} Level {n}: noch kein Skript")
                continue
            try:
                series["levels"][n - 1] = build_level(n, figs, skript)
                folder = out / f"bilder_{sid}_l{n}"
                pics = []
                prompts = to_english([prompt_for(s["bild"], figs) for s in skript])
                for i, pr in enumerate(prompts):
                    p = folder / f"{i:02d}.jpg"
                    src = imagegen.generate(pr[:880], p, seed=sum(map(ord, sid)) * 1000 + n * 100 + i, style=style)
                    print(f"  {sid} L{n} Bild {i + 1}/{len(skript)}: {src}")
                    pics.append(str(p))
                name = f"{sid}_{run_daily.slugify(title)}_level{n}.mp4"
                info = run_daily.render_lift(series, n, pics, out / name, backend=backend)
                print("fertig:", name, info.get("duration"))
            except Exception as e:
                print(f"{sid} Level {n} fehlgeschlagen: {e}")


if __name__ == "__main__":
    main()
