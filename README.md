# Roblox Creator Store Uploader

A robust, automated toolchain for uploading assets (Images, Decals, Audio, Models) to the Roblox Creator Store. It includes automatic preprocessing via Pixelfix, intelligent deduplication, EXIF metadata extraction, and state recovery for mass uploads.

---

## Features

* Mass Upload Support: Process single files, entire directories, or use JSON manifests for precise metadata control.
* Automatic Preprocessing (Pixelfix): Transparent PNGs are automatically processed to prevent pixel bleeding. The script dynamically checks for transparency to save processing time and bypasses the tool if unnecessary.
* Metadata Extraction: Reads internal file metadata (EXIF/Chunks) via Pillow to automatically populate asset descriptions.
* State Recovery & Resume: Built-in error handling allows the script to pause gracefully on network failures (auto-stops after 3 consecutive errors) or manual interruption (Ctrl+C). Resuming is possible via the start index parameter.
* Deduplication: Tracks file hashes in `upload_history.json` to prevent uploading the same asset multiple times.
* Auto-Watcher: Optional watcher script to monitor a directory and automatically upload new files as they are added.
* Graphical User Interface: Includes a modern dark-mode GUI for users who prefer a visual workflow.

---

## Setup

### 1. Install Dependencies

Install the required Python packages:

```bash
pip install requests rich python-dotenv watchdog Pillow customtkinter
```

Note: `requests`, `rich`, `Pillow` and `watchdog` are optional but highly recommended. The core uploader will fall back to standard libraries if they are missing, but features like rich console output, automatic EXIF extraction, and directory monitoring will be disabled.

### 2. Configuration (.env)

Create a `.env` file in the root directory to store your configuration. This prevents you from needing to pass credentials via command line arguments every time.

```env
ROBLOX_API_KEY=your_api_key_here
USER_ID=12345678
GROUP_ID=
DISCORD_WEBHOOK_URL=[https://discord.com/api/webhooks/](https://discord.com/api/webhooks/)...
```

### 3. API Key Setup

1. Navigate to the Roblox Creator Dashboard: [create.roblox.com/dashboard/credentials](https://create.roblox.com/dashboard/credentials)
2. Create a new API Key.
3. Assign the following permissions under the "Assets API": `asset:read` and `asset:write`.

---

## Usage: Command Line Interface (CLI)

The CLI tool (`uploader.py`) is designed for batch processing and CI/CD integration.

### Basic Examples

Upload a single file:
```bash
python uploader.py --user-id 12345 --asset-type Decal icon.png
```

Upload an entire directory:
```bash
python uploader.py --user-id 12345 --asset-type Image ./icons/
```

Upload using a manifest file (for individual names/descriptions per file):
```bash
python uploader.py --user-id 12345 --manifest manifest.example.json
```

Resume an interrupted batch upload starting at the 150th image:
```bash
python uploader.py --user-id 12345 --start-index 150 ./icons/
```

Upload for a Group:
```bash
python uploader.py --group-id 9876543 ./assets/
```

---

## Usage: Graphical User Interface (GUI)

A Tkinter/CustomTkinter-based interface is available for a streamlined experience without the command line.

To launch the GUI:
```bash
python gui.py
```

The GUI automatically loads your `.env` configuration and allows you to select input paths, asset types, and toggle preprocessing options visually.

---

## Interruptions and Resuming

The script is designed for high-volume uploads (e.g., 2000+ assets). 

1. **Manual Stop:** Pressing `Ctrl+C` will trigger a graceful exit. The script will finish the current operation, save the results, and display a command to resume exactly where you stopped.
2. **Auto-Stop:** If the script encounters 3 consecutive errors (e.g., due to internet loss), it will automatically stop to prevent the queue from filling with failures.
3. **Resuming:** Use the `--start-index` argument followed by the index number provided in the summary of the previous run.

---

## CLI Arguments Reference (`uploader.py`)

| Argument | Description |
| :--- | :--- |
| `input` | File or folder paths to upload (Required if no manifest is provided) |
| `--key` | Roblox API Key (defaults to `ROBLOX_API_KEY` env var) |
| `--user-id` | Upload as User ID (defaults to `USER_ID` env var) |
| `--group-id` | Upload as Group ID (defaults to `GROUP_ID` env var) |
| `--asset-type` | Asset type to create (e.g., Decal, Audio, Model) |
| `--manifest` | Path to a JSON manifest with asset metadata |
| `--name` | Display name (only applies to single file uploads) |
| `--description` | Default description for uploaded assets |
| `--no-pixelfix` | Disable automatic Pixelfix processing |
| `--no-dedup` | Force upload even if the file hash is already in the history |
| `--distribute` | Automatically configure the asset for the Creator Store |
| `--start-index` | Skip files in the queue until this index is reached |
| `--delay` | Pause between uploads in seconds to respect rate limits (Default: 1.2) |
| `--dry-run` | Simulate the entire process without sending data to Roblox |
| `--results` | Path to save the final upload results as a JSON file |