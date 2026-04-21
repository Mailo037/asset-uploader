# Roblox Creator Store Uploader

Automatic upload tool for Images, Decals, Audio, and Models to the Roblox Creator Store, featuring integrated **Pixelfix** preprocessing.

---

## 🛠 Setup

### 1. Install Dependencies
```bash
pip install requests rich python-dotenv watchdog
```
> [!TIP]
> `requests`, `rich`, `python-dotenv`, and `watchdog` are recommended. Without them, the scripts will run with limited functionality using standard library fallbacks.

### 2. Configuration (`.env`)
You can save your configuration in a `.env` file in the main directory so you don't have to enter it every time you run the tools.

Create a file named `.env`:
```env
ROBLOX_API_KEY=your_api_key_here
USER_ID=12345678
GROUP_ID=
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

### 3. API Key Setup
1. Open [create.roblox.com/dashboard/credentials](https://create.roblox.com/dashboard/credentials)
2. Create an API Key with Permissions: **Assets API** → `asset:read`, `asset:write`.

---

## 🖥 Graphical User Interface (GUI)
> [!NOTE]
> *Development in progress.* A sleek Tkinter-based GUI allows you to select paths, choose the Asset Type, and toggle options without using the command line.

To start the GUI:
```bash
python gui.py
```
*Note: Any credentials saved in your `.env` file will automatically be loaded into the GUI.*

---

## ⌨ CLI Usage

### Single File
```bash
python uploader.py --user-id 12345 --asset-type Decal icon.png
```

### Entire Folder
```bash
python uploader.py --user-id 12345 --asset-type Image ./icons/
```

### With Manifest (Individual names/descriptions per asset)
```bash
python uploader.py --user-id 12345 --manifest manifest.example.json
```

### Upload for a Group
```bash
python uploader.py --group-id 9876543 ./assets/
```

---

## CLI Arguments (`uploader.py`)

| Argument | Description |
| :--- | :--- |
| `target` | File or folder path to upload (Required) |
| `--key` | Roblox API Key (or `ROBLOX_API_KEY` env var) |
| `--user-id` | Upload as User ID |
| `--group-id` | Upload as Group ID |
| `--asset-type` | Asset type to create (e.g., Decal, Image, Model) |
| `--manifest` | JSON manifest with asset metadata |
| `--name` | Display name (only for single file uploads) |
| `--description` | Default description |
| `--no-pixelfix` | Skip the Pixelfix step |
| `--no-dedup` | Force upload even if already uploaded |
| `--distribute` | Configure Creator Store Distribution |
| `--dry-run` | Simulate without actually uploading |
| `--delay` | Pause between uploads in seconds (Default: 1.2) |
| `--results` | Save results as JSON |
