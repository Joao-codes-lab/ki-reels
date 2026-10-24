"""Schneller Bildtest ohne Gemini: Level-1-Bilder gespeicherter Serien mit allen Design-Varianten als Übersicht.

  python tools/bild_test.py data/series/de_frucht_*.json --out research/bildtest
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_daily  # noqa: E402
from reels import imagegen, scriptgen  # noqa: E402
from reels.render import F_BLACK  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("series", nargs="+")
    ap.add_argument("--out", default="research/bildtest")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tiles = []
    for k, f in enumerate(a.series):
        s = run_daily.load(Path(f), {})
        frame = Path(f).stem.split("_")[1]
        lv = s["levels"][0]
        base = scriptgen.FRAMES.get(frame, {}).get("style") or imagegen.STYLE
        for j, (model, extra) in enumerate(run_daily.DESIGN_VARIANTS):
            for i, scene in enumerate([lv["visual"]] + lv["scenes"][:1]):
                p = out / f"{Path(f).stem}_v{j}_{i}.jpg"
                src = imagegen.generate(run_daily.image_prompt(frame, lv, scene), p, w=576, h=1024, seed=99 + k,
                                        style=f"{base}, {extra}" if extra else base, model=model)
                print(p.name, src)
                im = Image.open(p).convert("RGB").resize((360, 640))
                d = ImageDraw.Draw(im)
                d.rectangle([0, 0, 360, 44], fill=(0, 0, 0))
                d.text((10, 6), f"{k}: v{j} {model} {src}"[:30], font=F_BLACK(26), fill=(255, 255, 255))
                tiles.append(im)
    cols = 6
    sheet = Image.new("RGB", (360 * cols, 640 * ((len(tiles) + cols - 1) // cols)), "black")
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * 360, (i // cols) * 640))
    sheet.save(out / "UEBERSICHT.jpg", quality=85)


if __name__ == "__main__":
    main()
