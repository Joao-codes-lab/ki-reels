"""Posting-Rhythmus und Hit-Muster der Vorbild-Accounts (nur Metadaten, keine Downloads).

  python tools/profile_stats.py _8_levels simpsonsvorhersage.n herr.amorim --max 60 --out research/rhythmus

Holt über Apify die letzten Reels je Account (Datum, Aufrufe, Likes, Kommentare, Länge, Caption) und schreibt
pro Account Kennzahlen: Posts pro Woche, Uhrzeiten (Berlin), Wochentage, Länge, Median-Aufrufe, Top 5 und
Flop 5. Danach erklärt Gemini, was Hits von Flops unterscheidet.
"""
import argparse
import datetime as dt
import json
import os
import statistics
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reels import scriptgen  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")
DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

WHY_PROMPT = """Du bist Analyst für virale Kurzvideos. Unten stehen die letzten Reels eines Instagram-Accounts mit
Aufrufen, Länge, Uhrzeit und Caption. Erkläre konkret und mit Zahlen, was die Hits von den Flops unterscheidet
(Thema, Hook in der Caption, Teil-Nummer der Serie, Länge, Uhrzeit, Wochentag) und was ein neuer Kanal daraus
übernehmen sollte. Antworte NUR mit JSON: {{"muster": [str, ...], "uebernehmen": [str, ...], "fazit": str}}
REELS:
{reels}"""


def fetch(user, n):
    body = json.dumps({"username": [user], "resultsLimit": n}).encode()
    url = ("https://api.apify.com/v2/acts/apify~instagram-reel-scraper/run-sync-get-dataset-items"
           f"?token={os.environ['APIFY_TOKEN']}&timeout=280")
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def summarize(user, items):
    rows = []
    for it in items:
        ts = it.get("timestamp")
        if not ts:
            continue
        t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(BERLIN)
        rows.append({"t": t, "views": it.get("videoPlayCount") or it.get("videoViewCount") or 0,
                     "likes": it.get("likesCount") or 0, "comments": it.get("commentsCount") or 0,
                     "sec": round(it.get("videoDuration") or 0), "code": it.get("shortCode"),
                     "caption": (it.get("caption") or "").replace("\n", " ")[:160]})
    rows.sort(key=lambda r: r["t"])
    if len(rows) < 2:
        return f"## {user}\n\nZu wenige Daten ({len(rows)} Reels).\n", rows
    span = max((rows[-1]["t"] - rows[0]["t"]).days, 1)
    views = [r["views"] for r in rows]
    hours = Counter(r["t"].hour for r in rows).most_common(4)
    days = Counter(DAYS[r["t"].weekday()] for r in rows).most_common(7)
    top = sorted(rows, key=lambda r: -r["views"])
    md = [f"## {user}", "",
          f"- Reels ausgewertet: {len(rows)} ({rows[0]['t']:%d.%m.%Y} bis {rows[-1]['t']:%d.%m.%Y})",
          f"- Rhythmus: {len(rows) / span * 7:.1f} Reels pro Woche",
          f"- Uhrzeiten (Berlin): " + ", ".join(f"{h}:00 ({c}x)" for h, c in hours),
          f"- Wochentage: " + ", ".join(f"{d} {c}x" for d, c in days),
          f"- Länge: Median {statistics.median(r['sec'] for r in rows)} s",
          f"- Aufrufe: Median {statistics.median(views):,.0f}, Max {max(views):,.0f}".replace(",", "."),
          f"- Kommentare pro 1.000 Aufrufe (Median): "
          f"{statistics.median(r['comments'] / max(r['views'], 1) * 1000 for r in rows):.1f}", "",
          "| | Datum | Aufrufe | Länge | Caption |", "|---|---|---|---|---|"]
    for tag, sel in (("Top", top[:5]), ("Flop", top[-5:])):
        for r in sel:
            md.append(f"| {tag} | {r['t']:%a %d.%m. %H:%M} | {r['views']:,} | {r['sec']} s | {r['caption'][:90]} |"
                      .replace(",", "."))
    return "\n".join(md) + "\n", rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("users", nargs="+")
    ap.add_argument("--max", type=int, default=60)
    ap.add_argument("--out", default="research/rhythmus")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    report = [f"# Posting-Rhythmus und Hit-Muster ({dt.date.today():%d.%m.%Y})", ""]
    for raw in a.users:
        user = raw.rstrip("/").split("/")[-1].lstrip("@")
        try:
            items = fetch(user, a.max)
        except Exception as e:
            report.append(f"## {user}\n\nAbruf fehlgeschlagen: {e}\n")
            continue
        md, rows = summarize(user, items)
        report.append(md)
        (out / f"{user}.json").write_text(json.dumps(
            [{**r, "t": r["t"].isoformat()} for r in rows], ensure_ascii=False, indent=1), encoding="utf-8")
        if rows:
            try:
                why = scriptgen.ask(WHY_PROMPT.format(reels=json.dumps(
                    [{"views": r["views"], "sec": r["sec"], "zeit": f"{r['t']:%a %H:%M}", "caption": r["caption"]}
                     for r in rows], ensure_ascii=False)))
                report.append("**Warum es viral geht:**\n\n" + "\n".join(f"- {m}" for m in why.get("muster", []))
                              + "\n\n**Für uns übernehmen:**\n\n" + "\n".join(f"- {m}" for m in why.get("uebernehmen", []))
                              + f"\n\n{why.get('fazit', '')}\n")
            except Exception as e:
                report.append(f"(Gemini-Auswertung fehlgeschlagen: {e})\n")
        print(md)
    (out / "RHYTHMUS.md").write_text("\n".join(report), encoding="utf-8")


if __name__ == "__main__":
    main()
