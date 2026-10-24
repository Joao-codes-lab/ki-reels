"""Stilproben: dieselbe Szene in verschiedenen Bildstilen, als beschriftete Übersicht.

  python tools/style_samples.py --out research/stile
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reels import imagegen  # noqa: E402
from reels.render import F_BLACK  # noqa: E402

SCENE = ("A tired young barista woman with a messy bun and a green apron counts coins from the tip jar behind the "
         "counter of a small corner café at night, worried look, a mysterious man in a dark suit leaves through the "
         "door in the background, rain outside")

STYLES = {
    "Papier-Diorama": "layered paper cut-out diorama, handmade craft paper textures, soft shadows between paper layers, "
                      "miniature stage lighting",
    "Knetfiguren": "claymation stop-motion scene, plasticine characters with fingerprints texture, handmade miniature "
                   "set, warm studio lighting",
    "Miniaturwelt": "isometric miniature tilt-shift diorama, tiny detailed world, toy-like characters, cinematic depth "
                    "of field",
    "Riso-Druck": "risograph print illustration, limited palette of fluorescent pink, teal and yellow, grainy texture, "
                  "slight misregistration, bold graphic shapes",
    "Neon-Noir": "neon noir graphic novel, deep blacks, glowing magenta and cyan neon light, rain reflections, "
                 "stylized characters with sharp shadows",
    "Holzschnitt modern": "modern ukiyo-e woodblock print style, flat colors, elegant line work, textured paper, "
                          "contemporary setting",
    "Filz-Stopmotion": "felt and wool stop-motion animation set, fuzzy textures, button eyes, cozy handmade look",
    "Tinte + Akzent": "high-contrast black and white ink comic, heavy brush strokes, one single accent color gold, "
                      "dramatic composition",
    "Low-Poly 3D": "low-poly 3D render, faceted geometric shapes, pastel gradient lighting, clean stylized characters",
    "Sitcom-Cartoon": imagegen.STYLE,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="research/stile")
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    tiles = []
    for name, style in STYLES.items():
        p = out / f"{name}.jpg"
        src = imagegen.generate(SCENE, p, w=576, h=1024, seed=4242,
                                style=f"{style}, no text, no letters, no watermark")
        print(f"{name}: {src}")
        im = Image.open(p).convert("RGB").resize((360, 640))
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, 360, 56], fill=(0, 0, 0))
        d.text((12, 10), name, font=F_BLACK(30), fill=(255, 255, 255))
        tiles.append(im)
    cols = 5
    sheet = Image.new("RGB", (360 * cols, 640 * ((len(tiles) + cols - 1) // cols)), "black")
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * 360, (i // cols) * 640))
    sheet.save(out / "UEBERSICHT.jpg", quality=88)


if __name__ == "__main__":
    main()
