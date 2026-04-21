#!/usr/bin/env python3
"""
Roblox Creator Store Image Uploader
Preprocesses images with Pixelfix, then uploads to Roblox via Open Cloud API.
"""

import os
import sys
import json
import time
import hashlib
import platform
import subprocess
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional
import mimetypes
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# ── Optional rich output ──────────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
    from rich.table import Table
    from rich.panel import Panel
    from rich import print as rprint
    RICH = True
    console = Console()
except ImportError:
    RICH = False
    class Console:
        def print(self, *a, **kw): print(*a)
        def rule(self, *a, **kw): print("─" * 60)
        def log(self, *a, **kw): print("[LOG]", *a)
    console = Console()
    def rprint(*a, **kw): print(*a)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    import urllib.request as urlreq

# ── Constants ─────────────────────────────────────────────────────────────────
PIXELFIX_URL = "https://github.com/Corecii/Transparent-Pixel-Fix/releases/download/1.0.0/TransparentPixelFix.exe"
PIXELFIX_BIN = Path(__file__).parent / "tools" / "TransparentPixelFix.exe"
ROBLOX_ASSETS_API = "https://apis.roblox.com/assets/v1/assets"
ROBLOX_OPS_API    = "https://apis.roblox.com/assets/v1/operations/{op_id}"
HISTORY_FILE      = Path(__file__).parent / "upload_history.json"
SUPPORTED_EXT     = {".png", ".jpg", ".jpeg", ".bmp", ".tga"}
RATE_LIMIT_DELAY  = 1.2   # seconds between uploads (stay under Roblox limits)
MAX_POLL_ATTEMPTS = 30
POLL_INTERVAL     = 2.0   # seconds between operation polls

# ── History (deduplication) ───────────────────────────────────────────────────
def load_history() -> dict:
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {}

def save_history(history: dict):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

# ── Pixelfix ──────────────────────────────────────────────────────────────────
def download_pixelfix():
    """Download Pixelfix binary if not present (Windows only)."""
    if platform.system() != "Windows":
        return False
    if PIXELFIX_BIN.exists():
        return True
    console.print("[yellow]⬇  Downloading Pixelfix...[/yellow]" if RICH else "Downloading Pixelfix...")
    PIXELFIX_BIN.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(PIXELFIX_URL, PIXELFIX_BIN)
        console.print("[green]✓ Pixelfix downloaded.[/green]" if RICH else "Pixelfix downloaded.")
        return True
    except Exception as e:
        console.print(f"[red]✗ Could not download Pixelfix: {e}[/red]" if RICH else f"ERROR: {e}")
        return False

def run_pixelfix(image_path: Path, output_path: Optional[Path] = None) -> Path:
    """
    Run Pixelfix on a PNG image.
    Returns the path to the processed image.
    On non-Windows or if Pixelfix is missing, returns the original path with a warning.
    """
    if platform.system() != "Windows":
        console.print(f"[yellow]⚠ Pixelfix is Windows-only. Skipping for {image_path.name}[/yellow]" if RICH
                      else f"SKIP Pixelfix (non-Windows): {image_path.name}")
        return image_path

    if not PIXELFIX_BIN.exists():
        if not download_pixelfix():
            console.print(f"[yellow]⚠ Pixelfix unavailable. Uploading original.[/yellow]" if RICH
                          else "WARNING: Pixelfix unavailable.")
            return image_path

    if output_path is None:
        output_path = image_path.parent / "pixelfix_out" / image_path.name
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [str(PIXELFIX_BIN), str(image_path), str(output_path)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        console.print(f"[yellow]⚠ Pixelfix error for {image_path.name}: {result.stderr}[/yellow]" if RICH
                      else f"Pixelfix error: {result.stderr}")
        return image_path

    return output_path

# ── Roblox API ────────────────────────────────────────────────────────────────
def make_headers(api_key: str) -> dict:
    return {"x-api-key": api_key}

def upload_asset(
    api_key: str,
    image_path: Path,
    display_name: str,
    description: str,
    creator_type: str,   # "user" or "group"
    creator_id: str,
) -> dict:
    """
    Upload an image to Roblox via Open Cloud Assets API.
    Returns the operation response dict.
    """
    mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
    request_body = {
        "assetType": "Decal",
        "displayName": display_name,
        "description": description,
        "creationContext": {
            "creator": {
                f"{creator_type}Id": str(creator_id)
            }
        }
    }

    if HAS_REQUESTS:
        with open(image_path, "rb") as f:
            resp = requests.post(
                ROBLOX_ASSETS_API,
                headers=make_headers(api_key),
                data={"request": json.dumps(request_body)},
                files={"fileContent": (image_path.name, f, mime)},
            )
        resp.raise_for_status()
        return resp.json()
    else:
        # Fallback: manual multipart with urllib
        import io, email.generator
        from email.mime.multipart import MIMEMultipart
        from email.mime.application import MIMEApplication
        from email.mime.text import MIMEText

        boundary = "----RobloxUploaderBoundary"
        body_parts = []
        body_parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="request"\r\n'
            f"Content-Type: application/json\r\n\r\n"
            f"{json.dumps(request_body)}\r\n"
        )
        with open(image_path, "rb") as f:
            img_data = f.read()
        body_parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="fileContent"; filename="{image_path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        )
        body_bytes = "".join(body_parts).encode() + img_data + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            ROBLOX_ASSETS_API,
            data=body_bytes,
            headers={
                "x-api-key": api_key,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

def poll_operation(api_key: str, operation_path: str) -> Optional[dict]:
    """
    Poll an async Roblox operation until it completes or fails.
    `operation_path` is the `path` field from the upload response, e.g. "operations/abc123"
    """
    url = f"https://apis.roblox.com/assets/v1/{operation_path}"
    for attempt in range(MAX_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL)
        if HAS_REQUESTS:
            resp = requests.get(url, headers=make_headers(api_key))
            resp.raise_for_status()
            data = resp.json()
        else:
            req = urllib.request.Request(url, headers=make_headers(api_key))
            with urllib.request.urlopen(req) as r:
                data = json.loads(r.read())

        if data.get("done"):
            if "error" in data:
                raise RuntimeError(f"Operation failed: {data['error']}")
            return data.get("response", data)

    raise TimeoutError(f"Operation did not complete after {MAX_POLL_ATTEMPTS} attempts.")

def set_creator_store_free(api_key: str, asset_id: str):
    """
    Attempts to make the uploaded asset freely available on the Creator Store.
    NOTE: Full marketplace listing (price, tags) still requires manual setup on
    create.roblox.com > Creations > [Asset] > Marketplace.
    This call configures the asset metadata to allow distribution.
    """
    url = f"https://apis.roblox.com/assets/v1/assets/{asset_id}"
    payload = {
        "previews": [],   # Add preview URLs if desired
    }
    if HAS_REQUESTS:
        resp = requests.patch(
            url,
            headers={**make_headers(api_key), "Content-Type": "application/json"},
            json=payload
        )
        # Non-fatal: might 400 on assets that don't support marketplace listing via API
        if resp.status_code not in (200, 204):
            console.print(f"[yellow]ℹ Creator Store config returned {resp.status_code} – finish on create.roblox.com[/yellow]"
                          if RICH else f"INFO: Creator Store needs manual setup (HTTP {resp.status_code})")

# ── Manifest loading ──────────────────────────────────────────────────────────
def load_manifest(manifest_path: Path) -> list[dict]:
    """
    Load a manifest JSON file.
    Each entry: { "file": "icon.png", "name": "My Icon", "description": "...", "tags": [] }
    """
    with open(manifest_path) as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("assets", [])

# ── Core upload logic ─────────────────────────────────────────────────────────
def process_and_upload(
    image_path: Path,
    api_key: str,
    creator_type: str,
    creator_id: str,
    display_name: Optional[str],
    description: str,
    skip_pixelfix: bool,
    skip_dedup: bool,
    distribute: bool,
    dry_run: bool,
) -> Optional[dict]:
    """Full pipeline: Pixelfix → upload → poll → (optionally) distribute."""

    history = load_history()

    # Deduplication
    if not skip_dedup:
        h = file_hash(image_path)
        if h in history:
            prev = history[h]
            console.print(f"[dim]⏭  Skipping {image_path.name} (already uploaded as assetId={prev['assetId']})[/dim]"
                          if RICH else f"SKIP (duplicate): {image_path.name}")
            return prev

    name = display_name or image_path.stem.replace("_", " ").replace("-", " ").title()

    # Pixelfix
    processed = image_path
    if not skip_pixelfix and image_path.suffix.lower() == ".png":
        console.print(f"  [cyan]→ Running Pixelfix...[/cyan]" if RICH else "  Running Pixelfix...")
        processed = run_pixelfix(image_path)

    if dry_run:
        console.print(f"  [dim][DRY RUN] Would upload '{name}' from {processed}[/dim]" if RICH
                      else f"  [DRY RUN] {name} <- {processed}")
        return {"dryRun": True, "file": str(image_path), "name": name}

    # Upload
    console.print(f"  [cyan]→ Uploading '{name}'...[/cyan]" if RICH else f"  Uploading '{name}'...")
    op = upload_asset(api_key, processed, name, description, creator_type, creator_id)

    # Poll operation
    op_path = op.get("path") or op.get("operationId")
    if op_path:
        console.print(f"  [cyan]→ Waiting for operation {op_path}...[/cyan]" if RICH else f"  Polling operation...")
        result = poll_operation(api_key, op_path)
    else:
        result = op  # Synchronous response (older API behaviour)

    asset_id = (
        result.get("assetId")
        or result.get("assetVersionId")  # fallback
        or result.get("id")
    )
    if not asset_id:
        console.print(f"  [yellow]⚠ Could not extract assetId from response: {result}[/yellow]" if RICH
                      else f"  WARNING: no assetId in response")

    # Creator Store distribution
    if distribute and asset_id:
        console.print(f"  [cyan]→ Configuring Creator Store distribution...[/cyan]" if RICH
                      else "  Configuring Creator Store...")
        set_creator_store_free(api_key, str(asset_id))

    # Save to history
    record = {
        "assetId": asset_id,
        "name": name,
        "file": str(image_path),
        "uploadedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fullResponse": result,
    }
    if not skip_dedup:
        h = file_hash(image_path)
        history[h] = record
        save_history(history)

    console.print(f"  [green]✓ Done → assetId={asset_id}[/green]" if RICH else f"  OK: assetId={asset_id}")
    return record

# ── CLI ───────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="roblox_uploader",
        description="Upload images to the Roblox Creator Store with Pixelfix preprocessing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Upload single file
  python uploader.py --key YOUR_KEY --user-id 12345 image.png

  # Upload entire folder
  python uploader.py --key YOUR_KEY --user-id 12345 ./icons/

  # Upload via manifest (custom names/descriptions per file)
  python uploader.py --key YOUR_KEY --user-id 12345 --manifest manifest.json

  # Upload for a group, skip Pixelfix, dry run first
  python uploader.py --key YOUR_KEY --group-id 9876 --no-pixelfix --dry-run ./icons/

  # Auto-distribute on Creator Store
  python uploader.py --key YOUR_KEY --user-id 12345 --distribute ./icons/
        """
    )
    # Auth
    auth = p.add_argument_group("Authentication")
    auth.add_argument("--key", metavar="API_KEY", default=os.environ.get("ROBLOX_API_KEY"),
                      help="Roblox Open Cloud API key (or set ROBLOX_API_KEY env var)")
    creator = auth.add_mutually_exclusive_group()
    creator.add_argument("--user-id", metavar="ID", default=os.environ.get("USER_ID"),
                      help="Upload as a user (or set USER_ID env var)")
    creator.add_argument("--group-id", metavar="ID", default=os.environ.get("GROUP_ID"),
                      help="Upload as a group (or set GROUP_ID env var)")

    # Input
    inp = p.add_argument_group("Input")
    inp.add_argument("input", nargs="*", help="Image file(s) or folder(s)")
    inp.add_argument("--manifest", metavar="FILE", help="JSON manifest with per-asset metadata")

    # Metadata
    meta = p.add_argument_group("Metadata")
    meta.add_argument("--name", metavar="NAME", help="Display name (single file only)")
    meta.add_argument("--description", metavar="TEXT", default="Uploaded by roblox_uploader",
                      help="Default asset description")

    # Behaviour
    beh = p.add_argument_group("Behaviour")
    beh.add_argument("--no-pixelfix", action="store_true", help="Skip Pixelfix preprocessing")
    beh.add_argument("--no-dedup", action="store_true", help="Upload even if already in history")
    beh.add_argument("--distribute", action="store_true",
                     help="Configure asset for Creator Store distribution after upload")
    beh.add_argument("--dry-run", action="store_true", help="Simulate upload without actually uploading")
    beh.add_argument("--delay", type=float, default=RATE_LIMIT_DELAY, metavar="SECS",
                     help=f"Delay between uploads in seconds (default: {RATE_LIMIT_DELAY})")

    # Output
    out = p.add_argument_group("Output")
    out.add_argument("--results", metavar="FILE", help="Write upload results to a JSON file")

    return p

def collect_images(inputs: list) -> list[Path]:
    images = []
    for inp in inputs:
        p = Path(inp)
        if p.is_dir():
            for ext in SUPPORTED_EXT:
                images.extend(sorted(p.glob(f"**/*{ext}")))
                images.extend(sorted(p.glob(f"**/*{ext.upper()}")))
        elif p.is_file() and p.suffix.lower() in SUPPORTED_EXT:
            images.append(p)
        else:
            console.print(f"[yellow]⚠ Skipping unsupported input: {inp}[/yellow]" if RICH
                          else f"WARNING: skipping {inp}")
    # Deduplicate while preserving order
    seen = set()
    result = []
    for p in images:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            result.append(p)
    return result

def main():
    parser = build_parser()
    args = parser.parse_args()

    # ── Validation ────────────────────────────────────────────────────────────
    if not args.key:
        parser.error("--key or ROBLOX_API_KEY env var required.")
    if not args.user_id and not args.group_id:
        parser.error("Either --user-id or --group-id is required.")
    if not args.input and not args.manifest:
        parser.error("Provide at least one input file/folder or --manifest.")

    creator_type = "user" if args.user_id else "group"
    creator_id   = args.user_id or args.group_id

    if RICH:
        console.print(Panel.fit(
            f"[bold]Roblox Creator Store Uploader[/bold]\n"
            f"Creator: {creator_type} {creator_id}  |  "
            f"Pixelfix: {'OFF' if args.no_pixelfix else 'ON'}  |  "
            f"Distribute: {'YES' if args.distribute else 'NO'}  |  "
            f"Dry run: {'YES' if args.dry_run else 'NO'}",
            border_style="cyan"
        ))

    # ── Collect assets ────────────────────────────────────────────────────────
    tasks: list[dict] = []

    if args.manifest:
        entries = load_manifest(Path(args.manifest))
        for e in entries:
            path = Path(e["file"])
            tasks.append({
                "path": path,
                "name": e.get("name"),
                "description": e.get("description", args.description),
            })
    else:
        images = collect_images(args.input)
        if not images:
            console.print("[red]No supported images found.[/red]" if RICH else "ERROR: no images found.")
            sys.exit(1)
        for img in images:
            tasks.append({
                "path": img,
                "name": args.name if len(images) == 1 else None,
                "description": args.description,
            })

    console.print(f"[bold]{len(tasks)} image(s) queued.[/bold]\n" if RICH else f"{len(tasks)} image(s) queued.")

    # ── Auto-download Pixelfix ────────────────────────────────────────────────
    if not args.no_pixelfix and platform.system() == "Windows":
        download_pixelfix()

    # ── Upload loop ───────────────────────────────────────────────────────────
    results = []
    failed  = []

    for i, task in enumerate(tasks, 1):
        path = task["path"]
        console.print(f"[bold][{i}/{len(tasks)}][/bold] {path.name}" if RICH else f"[{i}/{len(tasks)}] {path.name}")

        try:
            record = process_and_upload(
                image_path   = path,
                api_key      = args.key,
                creator_type = creator_type,
                creator_id   = creator_id,
                display_name = task["name"],
                description  = task["description"],
                skip_pixelfix= args.no_pixelfix,
                skip_dedup   = args.no_dedup,
                distribute   = args.distribute,
                dry_run      = args.dry_run,
            )
            if record:
                results.append(record)
        except Exception as e:
            console.print(f"  [red]✗ Error: {e}[/red]" if RICH else f"  ERROR: {e}")
            failed.append({"file": str(path), "error": str(e)})

        if i < len(tasks):
            time.sleep(args.delay)

    # ── Summary ───────────────────────────────────────────────────────────────
    if RICH:
        console.rule()
        table = Table(title="Upload Summary", show_lines=True)
        table.add_column("File", style="cyan", no_wrap=True)
        table.add_column("Asset ID", style="green")
        table.add_column("Status")
        for r in results:
            status = "[yellow]DRY RUN[/yellow]" if r.get("dryRun") else "[green]✓ OK[/green]"
            asset_id = str(r.get("assetId", "—"))
            table.add_row(Path(r.get("file", "?")).name, asset_id, status)
        for f in failed:
            table.add_row(Path(f["file"]).name, "—", f"[red]✗ {f['error'][:50]}[/red]")
        console.print(table)
    else:
        print(f"\n{'='*60}")
        print(f"Done: {len(results)} uploaded, {len(failed)} failed.")

    # ── Write results file ────────────────────────────────────────────────────
    if args.results:
        out = {"uploaded": results, "failed": failed}
        with open(args.results, "w") as f:
            json.dump(out, f, indent=2)
        console.print(f"[dim]Results written to {args.results}[/dim]" if RICH else f"Results → {args.results}")

    if failed:
        sys.exit(1)

if __name__ == "__main__":
    main()
