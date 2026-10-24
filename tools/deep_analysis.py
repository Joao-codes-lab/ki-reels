"""Tiefenanalyse der Vorbild-Accounts: Serien, Story-Typen, Art-Style und Gründe für Viralität.

  python tools/deep_analysis.py _8_levels simpsonsvorhersage.n herr.amorim --rhythmus research/rhythmus --top 8 --flop 3

Baut auf tools/profile_stats.py auf (dessen <account>.json mit den letzten ~50 Reels). Ohne diese Dateien holt es
die Metadaten selbst über Apify. Danach:
1. Serien-Auswertung aus den Captions: welche Serie, welcher Teil, Aufrufe je Teil, Abstand zwischen den Teilen.
2. Top- und Flop-Reels über Apify (Post-Links) laden, Gemini schaut jedes Video an und antwortet als JSON
   (Story-Typ, Gegenspieler, Stirn-Mechanik, Hook, Cliffhanger, Figuren, Art-Style, Ton, Gründe).
3. Gemini fasst alles zu einem Rezept für Storytelling und Design zusammen (nur Mechanik, keine Inhalte).
Ergebnis: <out>/TIEFENANALYSE.md, <out>/reels.json, <out>/rezept.json
"""
import argparse
import datetime as dt
import json
import os
import re
import statistics
import sys
import tempfile
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reels import scriptgen  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_stats  # noqa: E402

APIFY = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={token}&timeout=280"

VIDEO_PROMPT = """Du bist Analyst für virale Kurzvideos. Schau und hör dir dieses Reel genau an (Aufrufe: {views}, Caption: {caption}).
Beschreibe nur Mechanik und Stil, damit ein eigener Kanal mit eigenen Figuren und Geschichten davon lernen kann.
Antworte NUR mit JSON in diesem Schema (Deutsch):
{{"story_typ": "eins von: Level-Aufstieg, Bösewicht/Demütigung, Liebe/Eifersucht, Rache/Genugtuung, Geheimnis/Enthüllung, Wettbewerb, Familie, Sonstiges",
 "zusammenfassung": "3 Sätze, was passiert",
 "hook_erste_3s": "was man sieht und hört und warum man bleibt",
 "zentrale_frage": "die Frage, auf die das Video hinfiebert",
 "gegenspieler": {{"gibt_es": true, "wer": "", "warum_hasst_man_ihn": "", "bekommt_er_strafe": "ja/nein/später"}},
 "stirn_oder_status_mechanik": "sichtbarer Wert an Figuren (Zahl, Herz, Farbe ...) und wie er die Story treibt, sonst leer",
 "emotionen": ["Wut", "Mitleid", ...],
 "wendepunkte": ["Sekunde: Ereignis", ...],
 "ende": "wie das Video endet (Cliffhanger, Auflösung, CTA) und der genaue letzte Satz",
 "figuren": [{{"name_oder_typ": "", "aussehen": "Material, Form, Farben, Gesicht, Kleidung", "rolle": ""}}],
 "art_style": {{"render": "2D/3D, Look (z. B. Pixar-ähnlich), Detailgrad", "licht_und_farben": "", "kamera": "Einstellungen, Bewegung",
               "schnitte_pro_10s": 0, "untertitel": "Schrift, Größe, Farbe, Position, Wörter pro Einblendung",
               "wiederkehrende_elemente": ""}},
 "ton": {{"anzahl_stimmen": 0, "stimmen": "Typ, Emotion, Tempo, KI oder echt", "musik": "", "soundeffekte": ""}},
 "warum_viral": ["konkreter Grund", ...],
 "schwaechen": ["was das Video Aufrufe kostet", ...],
 "viral_score_1_10": 0}}"""

RECIPE_PROMPT = """Du bist Head of Content eines neuen faceless KI-Kanals (Instagram Reels + TikTok, Deutsch und Englisch).
Unten stehen Daten von drei sehr erfolgreichen Vorbild-Accounts: Posting-Kennzahlen, Serien-Auswertung und Video-Analysen
der Top- und Flop-Reels. Leite daraus belastbare Regeln ab, mit Zahlen aus den Daten. Nur Mechanik und Stil übernehmen,
keine Figuren, Namen oder Geschichten kopieren.
Antworte NUR mit JSON (Deutsch):
{{"top_erkenntnisse": ["mit Zahl belegt", ...],
 "story_typen_ranking": [{{"typ": "", "warum": "", "beleg": ""}}],
 "bösewicht_rezept": ["Regel", ...],
 "serien_rezept": {{"teile": "ideale Anzahl", "abstand": "zwischen Teilen", "cliffhanger": "wie", "caption": "wie"}},
 "hook_rezept": ["Regel", ...],
 "dramaturgie_sekunden": ["0-3 s: ...", "..."],
 "design_rezept": {{"figuren": "", "render": "", "farben_licht": "", "kamera_schnitt": "", "untertitel": "", "status_anzeige": ""}},
 "ton_rezept": {{"stimmen": "", "musik": "", "effekte": ""}},
 "posting_rezept": {{"pro_tag": "", "uhrzeiten_berlin": "", "laenge_s": ""}},
 "jury_kriterien": ["prüfbares Kriterium für Skript-Jury", ...],
 "verboten": ["was Flops gemeinsam haben", ...]}}
DATEN:
{data}"""


def apify(actor, body):
    url = APIFY.format(actor=actor, token=os.environ["APIFY_TOKEN"])
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def load_rows(user, rdir, n):
    f = Path(rdir) / f"{user}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    _, rows = profile_stats.summarize(user, profile_stats.fetch(user, n))
    return [{**r, "t": r["t"].isoformat()} for r in rows]


SERIES_RE = re.compile(r"^(?P<title>.*?)[\s\-–|:]*\b(?:(?:teil|part|folge|episode|level)\s*(?P<n>\d+)|(?P<end>ende|finale?|the end))\b"
                       r"(?P<rest>.*)$", re.I)


def series_of(caption):
    """'Der Millionärs-Ehemann – Teil 3 #...' -> ('Der Millionärs-Ehemann', 3); 'Level 6 | 8 Levels of X' -> ('8 Levels of X', 6)."""
    cap = re.sub(r"#\S+", "", caption or "").strip()
    m = SERIES_RE.match(cap)
    if not m:
        return None, None
    title = (m.group("title") or m.group("rest") or "").strip(" -–|:!") or "(ohne Titel)"
    return title, (int(m.group("n")) if m.group("n") else 99)


def series_report(user, rows):
    by, last = defaultdict(list), {}
    for r in sorted(rows, key=lambda x: x["t"]):
        title, n = series_of(r["caption"])
        r["serie"], r["teil"] = title, n
        if n is None:
            continue
        run = last.get(title, (0, 0))  # neue Staffel, wenn die Teil-Nummer wieder bei 1 anfängt
        run = (run[0] + 1, n) if n <= run[1] and n != 99 else (run[0] or 1, n)
        last[title] = run
        by[title if run[0] == 1 else f"{title} #{run[0]}"].append(r)
    md = [f"### Serien bei {user}", "",
          "| Serie | Teile | Aufrufe je Teil (Teil: Aufrufe) | Abstand zwischen Teilen (Median, h) |", "|---|---|---|---|"]
    per_part = defaultdict(list)
    for title, rs in sorted(by.items(), key=lambda kv: -max(x["views"] for x in kv[1])):
        rs.sort(key=lambda x: x["t"])
        gaps = [(dt.datetime.fromisoformat(b["t"]) - dt.datetime.fromisoformat(a["t"])).total_seconds() / 3600
                for a, b in zip(rs, rs[1:])]
        for x in rs:
            per_part[x["teil"]].append(x["views"])
        parts = ", ".join(f"{'Ende' if x['teil'] == 99 else x['teil']}: {x['views']:,}".replace(",", ".") for x in rs)
        md.append(f"| {title[:40]} | {len(rs)} | {parts} | {statistics.median(gaps):.1f} |" if gaps
                  else f"| {title[:40]} | 1 | {parts} | – |")
    if per_part:
        md += ["", "Median-Aufrufe nach Teil-Nummer: " + ", ".join(
            f"{'Ende' if k == 99 else k}: {statistics.median(v):,.0f} ({len(v)}x)".replace(",", ".")
            for k, v in sorted(per_part.items()))]
    loose = sum(1 for r in rows if r["teil"] is None)
    md.append(f"\nReels ohne Teil-Nummer: {loose} von {len(rows)}\n")
    return "\n".join(md)


def gemini_upload(path, key):
    """Gemini Files API (resumable), damit auch Videos über 20 MB gehen."""
    size = path.stat().st_size
    start = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={key}",
        json.dumps({"file": {"display_name": path.name}}).encode(),
        {"X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
         "X-Goog-Upload-Header-Content-Length": str(size), "X-Goog-Upload-Header-Content-Type": "video/mp4",
         "Content-Type": "application/json"})
    with urllib.request.urlopen(start, timeout=60) as r:
        up = r.headers["X-Goog-Upload-URL"]
    put = urllib.request.Request(up, path.read_bytes(), {"X-Goog-Upload-Command": "upload, finalize",
                                                         "X-Goog-Upload-Offset": "0", "Content-Length": str(size)})
    with urllib.request.urlopen(put, timeout=300) as r:
        f = json.load(r)["file"]
    for _ in range(40):  # warten bis Gemini das Video verarbeitet hat
        if f.get("state") == "ACTIVE":
            return f["uri"]
        time.sleep(3)
        with urllib.request.urlopen(f"https://generativelanguage.googleapis.com/v1beta/{f['name']}?key={key}",
                                    timeout=60) as r:
            f = json.load(r)
    raise RuntimeError("Video wurde nicht rechtzeitig verarbeitet")


def gemini_video(path, prompt):
    key = os.environ["GEMINI_API_KEY"]
    uri = gemini_upload(path, key)
    body = {"contents": [{"parts": [{"fileData": {"mimeType": "video/mp4", "fileUri": uri}}, {"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}}
    err = None
    for model in ("gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite"):
        for attempt in range(3):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    data = json.load(r)
                text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"] if not p.get("thought"))
                return json.loads(text[text.find("{"):text.rfind("}") + 1])
            except urllib.error.HTTPError as e:
                err = f"{model}: {e.code} {e.read()[:200]!r}"
                if e.code == 429:
                    time.sleep(30 * (attempt + 1))
                    continue
                break
            except Exception as e:
                err = f"{model}: {e}"
                break
    raise RuntimeError(err)


def video_urls(codes):
    items = apify("apify~instagram-scraper", {"directUrls": [f"https://www.instagram.com/p/{c}/" for c in codes],
                                              "resultsType": "posts", "resultsLimit": 1})
    return {it.get("shortCode"): it.get("videoUrl") for it in items if it.get("videoUrl")}


def reel_md(r, a):
    if "fehler" in a:
        return f"#### {r['views']:,} Aufrufe · {r['caption'][:80]}\n\nAnalyse fehlgeschlagen: {a['fehler']}\n".replace(",", ".")
    st, ton, g = a.get("art_style", {}), a.get("ton", {}), a.get("gegenspieler", {})
    lines = [f"#### {r['tag']} · {r['views']:,} Aufrufe · {r['sec']} s · {r['caption'][:80]}".replace(",", "."),
             f"https://www.instagram.com/p/{r['code']}/", "",
             f"- **Story-Typ:** {a.get('story_typ')} · Score {a.get('viral_score_1_10')}/10",
             f"- **Inhalt:** {a.get('zusammenfassung')}",
             f"- **Hook:** {a.get('hook_erste_3s')}",
             f"- **Zentrale Frage:** {a.get('zentrale_frage')}",
             f"- **Gegenspieler:** {g.get('wer') or '–'} ({g.get('warum_hasst_man_ihn') or ''}; Strafe: {g.get('bekommt_er_strafe')})",
             f"- **Status-Mechanik:** {a.get('stirn_oder_status_mechanik') or '–'}",
             f"- **Emotionen:** {', '.join(a.get('emotionen', []))}",
             f"- **Ende:** {a.get('ende')}",
             f"- **Figuren:** " + "; ".join(f"{f.get('name_oder_typ')}: {f.get('aussehen')}" for f in a.get("figuren", [])),
             f"- **Look:** {st.get('render')} | {st.get('licht_und_farben')} | Kamera: {st.get('kamera')} | "
             f"{st.get('schnitte_pro_10s')} Schnitte/10 s | Untertitel: {st.get('untertitel')}",
             f"- **Ton:** {ton.get('anzahl_stimmen')} Stimmen, {ton.get('stimmen')} | Musik: {ton.get('musik')} | SFX: {ton.get('soundeffekte')}",
             f"- **Warum viral:** " + "; ".join(a.get("warum_viral", [])),
             f"- **Schwächen:** " + "; ".join(a.get("schwaechen", [])), ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("users", nargs="+")
    ap.add_argument("--rhythmus", default="research/rhythmus")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--flop", type=int, default=3)
    ap.add_argument("--max", type=int, default=50)
    ap.add_argument("--out", default="research/tiefe")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    users = [u.rstrip("/").split("/")[-1].lstrip("@") for u in a.users]

    rows, picks, report = {}, [], [f"# Tiefenanalyse der Vorbilder ({dt.date.today():%d.%m.%Y})", ""]
    for u in users:
        rows[u] = load_rows(u, a.rhythmus, a.max)
        report.append(series_report(u, rows[u]))
        ranked = sorted(rows[u], key=lambda r: -r["views"])
        for tag, sel in (("Top", ranked[:a.top]), ("Flop", ranked[-a.flop:] if a.flop else [])):
            picks += [{**r, "user": u, "tag": tag} for r in sel]

    urls = {}
    try:
        urls = video_urls([p["code"] for p in picks])
    except Exception as e:
        print("Apify (Videolinks) fehlgeschlagen:", e)
    print(f"Videolinks: {len(urls)} von {len(picks)}")

    analyses = []
    with tempfile.TemporaryDirectory() as tmp:
        for p in picks:
            res = {"fehler": "kein Videolink"}
            if urls.get(p["code"]):
                mp4 = Path(tmp) / f"{p['code']}.mp4"
                try:
                    urllib.request.urlretrieve(urls[p["code"]], mp4)
                    res = gemini_video(mp4, VIDEO_PROMPT.format(views=p["views"], caption=p["caption"][:120]))
                except Exception as e:
                    res = {"fehler": str(e)[:300]}
                mp4.unlink(missing_ok=True)
                time.sleep(8)  # Free Tier: ca. 10 Anfragen pro Minute
            print(p["user"], p["code"], p["views"], res.get("story_typ") or res.get("fehler"))
            analyses.append({"reel": p, "analyse": res})
    (out / "reels.json").write_text(json.dumps(analyses, ensure_ascii=False, indent=1), encoding="utf-8")

    # Story-Typ gegen Aufrufe
    by_type = defaultdict(list)
    for x in analyses:
        if "story_typ" in x["analyse"]:
            by_type[x["analyse"]["story_typ"]].append(x["reel"]["views"])
    report += ["## Story-Typen der analysierten Reels", "", "| Story-Typ | Reels | Median-Aufrufe |", "|---|---|---|"]
    report += [f"| {t} | {len(v)} | {statistics.median(v):,.0f} |".replace(",", ".")
               for t, v in sorted(by_type.items(), key=lambda kv: -statistics.median(kv[1]))]

    stats = {u: {"reels": len(rows[u]),
                 "median_views": statistics.median([r["views"] for r in rows[u]]) if rows[u] else 0,
                 "posts": [{"zeit": r["t"][:16], "views": r["views"], "sec": r["sec"], "serie": r.get("serie"),
                            "teil": r.get("teil")} for r in rows[u]]} for u in users}
    compact = [{"user": x["reel"]["user"], "tag": x["reel"]["tag"], "views": x["reel"]["views"], **x["analyse"]}
               for x in analyses if "fehler" not in x["analyse"]]
    recipe = {}
    try:
        recipe = scriptgen.ask(RECIPE_PROMPT.format(data=json.dumps({"kennzahlen": stats, "videos": compact},
                                                                    ensure_ascii=False)[:600_000]))
        (out / "rezept.json").write_text(json.dumps(recipe, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        report.append(f"\n(Rezept fehlgeschlagen: {e})")
    if recipe:
        report += ["", "## Rezept (Gemini, aus allen Daten)", ""]
        for k, v in recipe.items():
            report.append(f"### {k}")
            if isinstance(v, list):
                report += [f"- {json.dumps(i, ensure_ascii=False) if isinstance(i, dict) else i}" for i in v]
            elif isinstance(v, dict):
                report += [f"- **{kk}:** {vv}" for kk, vv in v.items()]
            else:
                report.append(str(v))
            report.append("")

    report += ["## Einzelanalysen", ""]
    for u in users:
        report.append(f"### {u}\n")
        report += [reel_md(x["reel"], x["analyse"]) for x in analyses if x["reel"]["user"] == u]
    (out / "TIEFENANALYSE.md").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report[:60]))


if __name__ == "__main__":
    main()
