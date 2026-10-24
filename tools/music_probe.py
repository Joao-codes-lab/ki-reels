"""Hintergrundmusik von Vorbild-Reels bestimmen (Titel laut Instagram, Stil, Tempo, Stimmung, Lautstärke).

  python tools/music_probe.py https://www.instagram.com/p/De0X8-nsi-0/ [...] --out research/musik

Apify liefert pro Post die Musik-Angabe von Instagram (Titel, Künstler, Originalton ja/nein). Gemini hört sich
das Video an und beschreibt nur die Musik, damit wir eine eigene, lizenzfreie Entsprechung bauen können.
Audio wird nicht gespeichert.
"""
import argparse
import json
import tempfile
import time
import urllib.request
from pathlib import Path

import deep_analysis as deep

PROMPT = """Hör dir nur die Hintergrundmusik dieses Reels an (die Stimme ignorieren). Wir wollen eine eigene,
lizenzfreie Musik in derselben Wirkung erzeugen. Antworte NUR mit JSON (Deutsch):
{"genre": "", "bpm": 0, "tonart_oder_modus": "", "instrumente": ["..."], "stimmung": "",
 "aufbau": "wie sich die Musik über die Länge verändert (Sekunden)", "einsatz": "ab Sekunde X, Ein-/Ausblenden",
 "lautstaerke_zur_stimme": "z. B. Musik ca. 18 dB unter der Stimme", "drops_oder_akzente": "an welchen Stellen und wozu",
 "ende": "wie die Musik endet", "warum_sie_wirkt": "", "bekannter_track_oder_trend": "falls erkennbar, sonst leer",
 "nachbau_rezept": "konkrete Anleitung für einen Synthesizer: Akkordfolge, Bass, Drums, Effekte, Tempo"}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--out", default="research/musik")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    items = deep.apify("apify~instagram-scraper", {"directUrls": a.urls, "resultsType": "posts", "resultsLimit": 1})
    res, md = [], ["# Musik der Vorbild-Reels", ""]
    with tempfile.TemporaryDirectory() as tmp:
        for it in items:
            mi = it.get("musicInfo") or {}
            row = {"url": it.get("url"), "owner": it.get("ownerUsername"), "views": it.get("videoPlayCount"),
                   "caption": (it.get("caption") or "")[:80], "instagram_musik": mi}
            if it.get("videoUrl"):
                mp4 = Path(tmp) / "v.mp4"
                try:
                    urllib.request.urlretrieve(it["videoUrl"], mp4)
                    row["analyse"] = deep.gemini_video(mp4, PROMPT)
                except Exception as e:
                    row["analyse"] = {"fehler": str(e)[:300]}
                time.sleep(8)
            res.append(row)
            print(json.dumps(row, ensure_ascii=False)[:1500], flush=True)
            md += [f"## {row['owner']} · {row['caption']}", row["url"] or "", "",
                   f"- **Instagram-Angabe:** {mi.get('song_name') or mi.get('songName')} – "
                   f"{mi.get('artist_name') or mi.get('artistName')} (Originalton: "
                   f"{mi.get('uses_original_audio', mi.get('usesOriginalAudio'))})"]
            md += [f"- **{k}:** {v}" for k, v in (row.get("analyse") or {}).items()] + [""]
    (out / "musik.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "MUSIK.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    main()
