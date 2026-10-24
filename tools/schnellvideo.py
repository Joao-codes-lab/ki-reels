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
    ap.add_argument("--frame", default=None, help="Look überschreiben, z. B. fruchtmensch")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = Path(a.series)
    if f.suffix == ".json":
        s = run_daily.load(f, {})
        s.setdefault("lang", f.stem.split("_")[0])
        frame = a.frame or f.stem.split("_")[1]
    else:  # neues Thema: Skript schreiben (inkl. Skript-Jury)
        frame = a.frame or "frucht"
        s = run_daily.scriptgen.write_series(a.series, a.lang, frame)
        f = out / f"{a.lang}_{frame}_{run_daily.slugify(a.series)}.json"
        run_daily.save(f, s)
    pics, _ = run_daily.level_images(s, 1, frame, out / f"bilder_{frame}", seed=4711)
    backend = "eleven" if os.environ.get("ELEVENLABS_API_KEY") else "gemini"
    info = run_daily.render_lift(s, 1, pics, out / f"{f.stem}_{frame}_teil1.mp4", backend=backend)
    print("fertig:", info)


if __name__ == "__main__":
    main()
