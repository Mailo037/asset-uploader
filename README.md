# Roblox Creator Store Uploader

Automatisches Upload-Tool für Images/Icons auf den Roblox Creator Store,
mit integrierter Pixelfix-Vorverarbeitung.

---

## Setup

## Setup

```bash
pip install requests rich python-dotenv watchdog
```

`requests`, `rich`, `python-dotenv` und `watchdog` sind empfohlen. Ohne sie laufen die Scripte mit eingeschränkter Funktionalität (stdlib Fallbacks).

### Konfiguration (.env)

Du kannst deine Konfiguration in einer `.env` Datei im Hauptverzeichnis speichern, damit du sie nicht jedes Mal beim Ausführen angeben musst.

Erstelle eine Datei namens `.env`:

```env
ROBLOX_API_KEY=your_api_key_here
USER_ID=12345678
GROUP_ID=
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

1. Öffne [create.roblox.com/credentials](https://create.roblox.com/dashboard/credentials)
2. Erstelle einen API Key mit Permission: **Assets API** → `asset:read`, `asset:write`.

---

## Benutzung

### Einzelne Datei
```bash
python uploader.py --user-id 12345 icon.png
```

### Ganzer Ordner
```bash
python uploader.py --user-id 12345 ./icons/
```

### Mit Manifest (individuelle Namen/Beschreibungen pro Asset)
```bash
python uploader.py --user-id 12345 --manifest manifest.example.json
```

### Für eine Gruppe hochladen
```bash
python uploader.py --group-id 9876 ./icons/
```

### Creator Store Distribution aktivieren
```bash
python uploader.py --user-id 12345 --distribute ./icons/
```
> **Hinweis:** Das finale Freischalten im Marketplace (Preis = 0, Tags, Thumbnail)
> muss einmalig auf [create.roblox.com](https://create.roblox.com) gemacht werden.
> Der `--distribute` Flag bereitet das Asset API-seitig vor.

### Pixelfix überspringen
```bash
python uploader.py --user-id 12345 --no-pixelfix ./icons/
```

### Dry Run (ohne echten Upload)
```bash
python uploader.py --user-id 12345 --dry-run ./icons/
```

### Ergebnisse als JSON speichern
```bash
python uploader.py --user-id 12345 --results results.json ./icons/
```

---

## Pixelfix

[Pixelfix (TransparentPixelFix)](https://github.com/Corecii/Transparent-Pixel-Fix)
wird automatisch in `tools/TransparentPixelFix.exe` heruntergeladen, wenn es fehlt.

- Nur auf **Windows** verfügbar
- Wird nur auf `.png`-Dateien angewendet
- Auf anderen Betriebssystemen wird der Schritt übersprungen

Was Pixelfix macht: Es setzt die RGB-Werte von vollständig transparenten Pixeln auf
die nächstgelegene sichtbare Farbe. Ohne das Farb-Bleeding bei Roblox-Decals und
in GUIs mit `ImageLabel`/`ImageButton`.

---

## Deduplication

Bereits hochgeladene Dateien werden via SHA-256-Hash erkannt und übersprungen.
History wird in `upload_history.json` gespeichert.

Mit `--no-dedup` deaktivieren.

---

## Manifest Format

```json
[
  {
    "file": "icons/sword.png",
    "name": "Sharp Sword Icon",
    "description": "A clean 256x256 sword icon."
  }
]
```

---

## Alle CLI-Optionen

| Flag             | Beschreibung                                          |
|------------------|-------------------------------------------------------|
| `--key`          | Roblox API Key (oder `ROBLOX_API_KEY` env var)       |
| `--user-id`      | Upload als User                                       |
| `--group-id`     | Upload als Group                                      |
| `--manifest`     | JSON-Manifest mit Asset-Metadaten                     |
| `--name`         | Anzeigename (nur bei Einzeldatei)                     |
| `--description`  | Standard-Beschreibung                                 |
| `--no-pixelfix`  | Pixelfix überspringen                                 |
| `--no-dedup`     | Bereits hochgeladene erneut hochladen                 |
| `--distribute`   | Creator Store Distribution konfigurieren              |
| `--dry-run`      | Simulieren ohne echten Upload                         |
| `--delay`        | Pause zwischen Uploads in Sekunden (Standard: 1.2)    |
| `--results`      | Ergebnisse als JSON speichern                         |

---

## Ideen für Erweiterungen

- **Auto-Resize**: Bilder vor dem Upload auf Roblox-konforme Größen skalieren
  (512×512, 1024×1024) mit Pillow
- **Thumbnail-Generator**: Automatisch Vorschaubilder für den Creator Store generieren
- **Tag-System**: Tags aus Dateinamen oder Manifest extrahieren und setzen
- **Watch Mode**: Ordner überwachen und neue Dateien automatisch hochladen (`watchdog`)
- **GUI**: Tkinter oder PyQt6 Drag & Drop Interface
- **CI/CD Integration**: GitHub Actions Workflow für automatische Uploads bei Commits
- **Roblox Studio Plugin**: Direkter Upload aus Studio heraus via Companion Script
- **Sprite Sheet Splitter**: Automatisch Sprite Sheets in Einzelbilder aufteilen und
  als Collection hochladen
- **Discord Webhook**: Nach erfolgreichen Uploads eine Benachrichtigung posten
