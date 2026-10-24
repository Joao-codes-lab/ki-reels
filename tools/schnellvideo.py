"""Ein einzelnes Video schnell rendern (Level 1 einer gespeicherten Serie), ohne Ideen-Battle.

  python tools/schnellvideo.py data/series/de_frucht_das_monatliche_dating_app_budget.json --out /tmp/research/schnell
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_daily  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("series", help="Pfad zu einer gespeicherten Serie ODER ein neues Thema (z. B. 'Gehalt nach dem Studium')")
    ap.add_argument("--lang", default="de")
    ap.add_argument("--out", default="research/schnell")
    ap.add_argument("--frame", default=None, help="Look(s) überschreiben, z. B. fruchtmensch oder frucht,fruchtmensch")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = Path(a.series)
    if f.suffix == ".json":
        s = run_daily.load(f, {})
        s.setdefault("lang", f.stem.split("_")[0])
        frames = (a.frame or f.stem.split("_")[1]).split(",")
    else:  # neues Thema: Skript schreiben (inkl. Skript-Jury)
        frames = (a.frame or "frucht").split(",")
        s = run_daily.scriptgen.write_series(a.series, a.lang, frames[0])
        f = out / f"{a.lang}_{frames[0]}_{run_daily.slugify(a.series)}.json"
        run_daily.save(f, s)
    backend = "eleven" if os.environ.get("ELEVENLABS_API_KEY") else "gemini"
    for frame in frames:  # dieselbe Geschichte in mehreren Looks zum Vergleich
        s["levels"][0].pop("quote_image", None)
        pics, _ = run_daily.level_images(s, 1, frame, out / f"bilder_{f.stem}_{frame}", seed=4711)
        info = run_daily.render_lift(s, 1, pics, out / f"{f.stem}_{frame}_teil1.mp4", backend=backend)
        print("fertig:", info)


if __name__ == "__main__":
    main()
