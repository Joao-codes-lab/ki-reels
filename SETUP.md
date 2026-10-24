# Einrichtung: was João einmalig erledigen muss

Danach läuft alles automatisch: Jeden Morgen schreibt eine KI ein neues „Die 8 Level von …“-Skript auf Deutsch und Englisch, das Video wird gerendert und über Buffer auf TikTok und Instagram eingeplant.

Dauer insgesamt: ca. 45 Minuten.

## 1. GitHub-Repository (5 Min)
1. Auf github.com → **New repository**
2. Name: `ki-reels`, Sichtbarkeit: **Public** (öffentlich = unbegrenzt kostenlose Rechenzeit und öffentliche Video-Links, die Buffer braucht; im Code stehen keine Passwörter)
3. Ohne README anlegen. Claude schiebt den Code selbst hinein.

## 2. Kostenloser KI-Schlüssel (3 Min)
1. https://aistudio.google.com → mit Google anmelden → **Get API key** → **Create API key**
2. Im Repo: **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `GEMINI_API_KEY`, Wert: der Schlüssel
3. Schlüssel nie in den Chat kopieren.

## 3. Accounts pro Sprache (je 10 Min)
Für **Deutsch** und **Englisch** jeweils:
1. Neue Gmail-Adresse (z. B. weristlevel8@gmail.com / whoislevel8@gmail.com)
2. **TikTok**-Account mit dieser Mail (persönliches Konto lassen, das braucht man später für Creator Rewards)
3. **Instagram**-Account mit dieser Mail → Einstellungen → **Professionelles Konto → Creator**
4. Nutzernamen (entschieden 2026-10-24): DE **@wer.ist.level8** (Anzeigename „Wer ist Level 8? 🍎“), EN **@who.is.level8** („Who is Level 8? 🍎“). Reserve gegen Kopierer: @weristlevel8 / @whoislevel8.
5. Bio: DE „Welches Level bist du? 👇 | Jeden Tag ein neues Level“, EN „What level are you? 👇 | A new level every day“

Tipp: Accounts nicht alle in derselben Minute vom selben Handy anlegen, sondern über den Tag verteilen. Ein paar Videos von Hand anschauen und liken, bevor das erste Video kommt.

## 4. Buffer (je 5 Min, ein Konto pro Sprache)
1. https://buffer.com → kostenlos registrieren mit der Gmail-Adresse der Sprache
2. TikTok- und Instagram-Account dieser Sprache verbinden
3. https://publish.buffer.com/settings/api → **API-Schlüssel erstellen**
4. Im GitHub-Repo als Secret speichern: `BUFFER_KEY_DE` bzw. `BUFFER_KEY_EN`
5. In Buffer bei jedem Kanal die Posting-Zeiten einstellen: 1× täglich, z. B. 18:00

## 5. Claude Bescheid geben
Kurz schreiben „Repo ist da“. Claude schiebt den Code hoch, schaltet GitHub Pages ein und startet den ersten Testlauf.

## Rechtliches (vor dem ersten Euro)
- Affiliate-Links kennzeichnen (z. B. „Werbung“ / *-Hinweis)
- Impressum im Link in der Bio, sobald Links mit Provision drin sind
- Einnahmen: Gewerbe anmelden (Kleinunternehmerregelung bis 25.000 € Vorjahresumsatz)

## 6. Shop für den Prompt-Guide (10 Min)
1. https://payhip.com → kostenlos registrieren (Free-Plan: 5 % Gebühr, keine Grundkosten)
2. Auszahlung mit PayPal verbinden
3. **Add product → Digital product**, PDF `Die 8 Level Prompt-Bibliothek.pdf` hochladen, Titel/Beschreibung/Preis aus `Verkaufstext.md` übernehmen
4. Link zum Produkt in die Bio aller Accounts (oder Claude schickt dir eine Link-Seite)
5. Impressum: Payhip-Shop und Bio brauchen ein Impressum mit ladungsfähiger Adresse, sobald verkauft wird
