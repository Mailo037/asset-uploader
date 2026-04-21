#!/usr/bin/env python3
"""
Roblox Uploader – Watch Mode
Watches a folder for new images, handles sprite sheet batches,
uploads sequentially, and notifies via Discord webhook.

Folder structure expected:
  watch_dir/
  ├── regular_icon.png          ← uploaded as single asset
  ├── another_logo.png
  └── sprite-sheets/            ← (configurable via --sprite-dir)
      ├── PlayerRun/            ← subfolder name = universal batch name
      │   ├── anim_001.png      ← ANY naming; numbers are extracted
      │   ├── anim_002.png
      │   └── anim_003.png
      └── EnemyWalk/
          ├── sheet_1.png
          └── sheet_2.png

Usage:
  python watcher.py --key YOUR_KEY --user-id 12345 --watch-dir ./assets
  python watcher.py --key YOUR_KEY --user-id 12345 --watch-dir ./assets \\
      --sprite-dir sprite-sheets --debounce 4 --webhook https://discord.com/api/webhooks/...
"""

import os
import re
import sys
import json
import time
import threading
import platform
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# ── Optional deps ─────────────────────────────────────────────────────────────
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    import urllib.request, urllib.parse

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    RICH = True
    console = Console()
except ImportError:
    RICH = False
    class Console:
        def print(self, *a, **kw): print(*a)
        def rule(self, *a, **kw): print("─" * 60)
        def log(self, *a, **kw): print("[LOG]", *a)
    console = Console()

# Import shared helpers from uploader.py (must be in same directory)
sys.path.insert(0, str(Path(__file__).parent))
try:
    from uploader import (
        process_and_upload, load_history, save_history, file_hash,
        SUPPORTED_EXT, download_pixelfix,
    )
    UPLOADER_AVAILABLE = True
except ImportError as e:
    console.print(f"[red]ERROR: uploader.py not found or broken: {e}[/red]" if RICH else f"ERROR: {e}")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# Sprite sheet utilities
# ─────────────────────────────────────────────────────────────────────────────

def extract_frame_number(filename: str) -> Optional[int]:
    """
    Extract the trailing integer from a filename stem.
    e.g. "file_rbx 3" → 3, "anim_007" → 7, "sheet2" → 2
    Returns None if no number found.
    """
    stem = Path(filename).stem
    match = re.search(r"(\d+)\s*$", stem)
    if match:
        return int(match.group(1))
    # Also try first number as fallback
    match = re.search(r"(\d+)", stem)
    return int(match.group(1)) if match else None

def normalize_sprite_name(universal_name: str, frame_number: int) -> str:
    """Build final asset display name: 'PlayerRun 3'"""
    return f"{universal_name} {frame_number}"

def sort_sprite_files(files: list[Path]) -> list[tuple[int, Path]]:
    """
    Sort sprite files by their embedded frame number.
    Returns list of (frame_number, path) tuples.
    Files without a number get assigned sequential numbers at the end.
    """
    numbered = []
    unnumbered = []
    for f in files:
        n = extract_frame_number(f.name)
        if n is not None:
            numbered.append((n, f))
        else:
            unnumbered.append(f)

    numbered.sort(key=lambda x: x[0])

    # Re-number gaps: if frames are 1,2,4,7 → keep original numbers
    # (Roblox scripts might rely on these; we preserve them)
    if unnumbered:
        next_n = (numbered[-1][0] + 1) if numbered else 1
        for f in unnumbered:
            numbered.append((next_n, f))
            next_n += 1

    return numbered

# ─────────────────────────────────────────────────────────────────────────────
# Discord Webhook
# ─────────────────────────────────────────────────────────────────────────────

ROBLOX_ASSET_URL = "https://www.roblox.com/catalog/{asset_id}"

def discord_notify(
    webhook_url: str,
    batch_name: str,
    results: list[dict],      # [{"frame": int, "name": str, "assetId": str}, ...]
    failed: list[dict],
    batch_type: str = "single",  # "single" | "sprite_sheet"
):
    """Send a Discord webhook embed with upload results."""
    if not webhook_url:
        return

    success_count = len([r for r in results if not r.get("dryRun") and r.get("assetId")])
    fail_count    = len(failed)
    color         = 0x00C853 if fail_count == 0 else (0xFF6D00 if success_count > 0 else 0xD50000)

    # Build fields
    fields = []

    if batch_type == "sprite_sheet":
        # List all frame → asset ID mappings (Discord has a 25 field limit)
        id_lines = []
        for r in results:
            aid = r.get("assetId", "?")
            frame = r.get("frame", "?")
            name  = r.get("name", "?")
            url   = ROBLOX_ASSET_URL.format(asset_id=aid) if aid != "?" else None
            line  = f"`{frame}` → [{aid}]({url})" if url else f"`{frame}` → `{aid}`"
            id_lines.append(line)

        # Split into chunks of ~10 to avoid hitting 1024 char field limit
        chunk_size = 10
        for i in range(0, len(id_lines), chunk_size):
            chunk = id_lines[i:i + chunk_size]
            fields.append({
                "name": f"Asset IDs (frames {i+1}–{min(i+chunk_size, len(id_lines))})",
                "value": "\n".join(chunk),
                "inline": False,
            })

        # Lua snippet for convenient use in scripts
        ids_array = ", ".join(str(r.get("assetId", 0)) for r in results)
        lua_snippet = f"local {batch_name.replace(' ', '')}IDs = {{ {ids_array} }}"
        fields.append({
            "name": "📋 Lua Snippet",
            "value": f"```lua\n{lua_snippet[:900]}\n```",
            "inline": False,
        })
    else:
        # Single uploads: simple list
        lines = []
        for r in results:
            aid  = r.get("assetId", "?")
            name = r.get("name", Path(r.get("file", "?")).name)
            url  = ROBLOX_ASSET_URL.format(asset_id=aid) if aid != "?" else None
            lines.append(f"**{name}** → [{aid}]({url})" if url else f"**{name}** → `{aid}`")
        if lines:
            fields.append({"name": "Uploaded Assets", "value": "\n".join(lines[:20]), "inline": False})

    if failed:
        fail_lines = [f"❌ `{Path(f['file']).name}`: {f['error'][:80]}" for f in failed[:5]]
        fields.append({"name": "Failures", "value": "\n".join(fail_lines), "inline": False})

    embed = {
        "title": f"{'🎞️ Sprite Sheet' if batch_type == 'sprite_sheet' else '🖼️ Upload'}: **{batch_name}**",
        "color": color,
        "fields": fields,
        "footer": {"text": f"Roblox Uploader • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    stats_parts = [f"✅ {success_count} uploaded"]
    if fail_count:
        stats_parts.append(f"❌ {fail_count} failed")
    if batch_type == "sprite_sheet":
        stats_parts.append(f"🎞️ {len(results)} frames")
    embed["description"] = "  •  ".join(stats_parts)

    payload = {"embeds": [embed], "username": "Roblox Uploader"}

    try:
        if HAS_REQUESTS:
            r = requests.post(webhook_url, json=payload, timeout=10)
            r.raise_for_status()
        else:
            data = json.dumps(payload).encode()
            req  = urllib.request.Request(
                webhook_url, data=data,
                headers={"Content-Type": "application/json"}, method="POST"
            )
            urllib.request.urlopen(req, timeout=10)
        console.print("[dim]  📨 Discord notified.[/dim]" if RICH else "  Discord notified.")
    except Exception as e:
        console.print(f"[yellow]  ⚠ Discord webhook failed: {e}[/yellow]" if RICH else f"  Discord warn: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Batch processor
# ─────────────────────────────────────────────────────────────────────────────

class UploadConfig:
    """Holds all settings passed down from CLI."""
    def __init__(self, api_key, creator_type, creator_id, skip_pixelfix,
                 skip_dedup, distribute, dry_run, webhook_url, upload_delay):
        self.api_key       = api_key
        self.creator_type  = creator_type
        self.creator_id    = creator_id
        self.skip_pixelfix = skip_pixelfix
        self.skip_dedup    = skip_dedup
        self.distribute    = distribute
        self.dry_run       = dry_run
        self.webhook_url   = webhook_url
        self.upload_delay  = upload_delay

def upload_single_image(path: Path, cfg: UploadConfig) -> Optional[dict]:
    """Upload a single, non-sprite-sheet image."""
    console.print(f"\n[bold cyan]🖼  Single upload:[/bold cyan] {path.name}" if RICH else f"\nSingle: {path.name}")
    try:
        record = process_and_upload(
            image_path   = path,
            api_key      = cfg.api_key,
            creator_type = cfg.creator_type,
            creator_id   = cfg.creator_id,
            display_name = None,   # uses stem
            description  = "Uploaded by Roblox Watcher",
            skip_pixelfix= cfg.skip_pixelfix,
            skip_dedup   = cfg.skip_dedup,
            distribute   = cfg.distribute,
            dry_run      = cfg.dry_run,
        )
        if record and cfg.webhook_url:
            discord_notify(
                webhook_url = cfg.webhook_url,
                batch_name  = path.stem,
                results     = [record],
                failed      = [],
                batch_type  = "single",
            )
        return record
    except Exception as e:
        console.print(f"  [red]✗ {e}[/red]" if RICH else f"  ERROR: {e}")
        if cfg.webhook_url:
            discord_notify(cfg.webhook_url, path.stem, [], [{"file": str(path), "error": str(e)}], "single")
        return None

def upload_sprite_batch(batch_dir: Path, universal_name: str, cfg: UploadConfig):
    """
    Upload all frames in a sprite sheet subfolder sequentially.
    Preserves frame order; strips original prefix, applies universal_name.
    """
    console.print(f"\n[bold magenta]🎞  Sprite batch:[/bold magenta] [bold]{universal_name}[/bold]  ({batch_dir})"
                  if RICH else f"\nSprite batch: {universal_name}")

    # Collect supported images
    raw_files = [
        f for f in batch_dir.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXT
    ]
    if not raw_files:
        console.print("  [yellow]No images found in batch dir.[/yellow]" if RICH else "  No images.")
        return

    sorted_frames = sort_sprite_files(raw_files)
    console.print(f"  [dim]{len(sorted_frames)} frame(s) detected.[/dim]" if RICH else f"  {len(sorted_frames)} frames.")

    results = []
    failed  = []

    for i, (frame_num, file_path) in enumerate(sorted_frames):
        display_name = normalize_sprite_name(universal_name, frame_num)
        console.print(
            f"  [bold][{i+1}/{len(sorted_frames)}][/bold] "
            f"[cyan]{file_path.name}[/cyan] → [green]{display_name}[/green]"
            if RICH else f"  [{i+1}/{len(sorted_frames)}] {file_path.name} → {display_name}"
        )

        try:
            record = process_and_upload(
                image_path   = file_path,
                api_key      = cfg.api_key,
                creator_type = cfg.creator_type,
                creator_id   = cfg.creator_id,
                display_name = display_name,
                description  = f"Frame {frame_num} of sprite sheet '{universal_name}'",
                skip_pixelfix= cfg.skip_pixelfix,
                skip_dedup   = cfg.skip_dedup,
                distribute   = cfg.distribute,
                dry_run      = cfg.dry_run,
            )
            if record:
                record["frame"] = frame_num
                record["name"]  = display_name
                results.append(record)
        except Exception as e:
            console.print(f"    [red]✗ {e}[/red]" if RICH else f"    ERROR: {e}")
            failed.append({"file": str(file_path), "frame": frame_num, "error": str(e)})

        if i < len(sorted_frames) - 1:
            time.sleep(cfg.upload_delay)

    # ── Print ordered ID table ─────────────────────────────────────────────
    if RICH and results:
        table = Table(title=f"[bold]{universal_name}[/bold] – Asset IDs", show_lines=True)
        table.add_column("Frame", style="dim", justify="right")
        table.add_column("Display Name", style="cyan")
        table.add_column("Asset ID", style="green bold")
        for r in results:
            aid = str(r.get("assetId", "DRY RUN"))
            table.add_row(str(r["frame"]), r["name"], aid)
        console.print(table)

        # Lua snippet
        ids_lua = ", ".join(str(r.get("assetId", 0)) for r in results)
        varname = re.sub(r"[^a-zA-Z0-9]", "", universal_name)
        console.print(Panel(
            f"[bold yellow]-- Lua (sequential IDs)[/bold yellow]\n"
            f"[white]local {varname}IDs = {{ {ids_lua} }}[/white]",
            border_style="yellow", expand=False
        ))
    else:
        print(f"\nOrdered Asset IDs for '{universal_name}':")
        for r in results:
            print(f"  Frame {r['frame']:>3}: {r.get('assetId', 'N/A')}")

    if cfg.webhook_url:
        discord_notify(cfg.webhook_url, universal_name, results, failed, "sprite_sheet")

# ─────────────────────────────────────────────────────────────────────────────
# Watch handler (watchdog)
# ─────────────────────────────────────────────────────────────────────────────

class RobloxWatchHandler(FileSystemEventHandler):
    """
    Watches a directory for new/modified image files.
    - Files directly in watch_dir    → single upload
    - Files in watch_dir/sprite_dir/ → sprite sheet batch upload
    
    Uses debouncing: waits `debounce_secs` after the last change
    in a sprite folder before processing the whole batch.
    """

    def __init__(
        self,
        watch_dir:    Path,
        sprite_dir:   str,
        cfg:          UploadConfig,
        debounce_secs: float = 3.0,
    ):
        super().__init__()
        self.watch_dir     = watch_dir.resolve()
        self.sprite_dir    = sprite_dir
        self.cfg           = cfg
        self.debounce_secs = debounce_secs

        # Map of sprite_batch_dir_path → threading.Timer
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

        # Track single files already seen (avoid double-fire)
        self._seen_singles: set[str] = set()

    def _is_sprite_file(self, path: Path) -> Optional[Path]:
        """
        If `path` is inside the sprite-sheets folder (in any subfolder),
        return the immediate subfolder (= batch dir). Otherwise None.
        """
        try:
            rel = path.relative_to(self.watch_dir / self.sprite_dir)
            # Must be exactly one level deep (batch_name/file.png)
            parts = rel.parts
            if len(parts) == 2:
                return self.watch_dir / self.sprite_dir / parts[0]
        except ValueError:
            pass
        return None

    def _schedule_batch(self, batch_dir: Path):
        """(Re)start debounce timer for a sprite batch folder."""
        key = str(batch_dir)
        with self._lock:
            if key in self._timers:
                self._timers[key].cancel()
            t = threading.Timer(
                self.debounce_secs,
                self._fire_batch,
                args=[batch_dir],
            )
            t.daemon = True
            self._timers[key] = t
            t.start()

    def _fire_batch(self, batch_dir: Path):
        """Called after debounce – process the sprite batch."""
        with self._lock:
            self._timers.pop(str(batch_dir), None)
        universal_name = batch_dir.name
        upload_sprite_batch(batch_dir, universal_name, self.cfg)

    def on_created(self, event):
        if event.is_directory:
            return
        self._handle(Path(event.src_path))

    def on_modified(self, event):
        if event.is_directory:
            return
        self._handle(Path(event.src_path))

    def on_moved(self, event):
        if event.is_directory:
            return
        self._handle(Path(event.dest_path))

    def _handle(self, path: Path):
        path = path.resolve()
        if path.suffix.lower() not in SUPPORTED_EXT:
            return

        batch_dir = self._is_sprite_file(path)
        if batch_dir:
            console.print(f"[dim]  📁 Sprite file detected: {path.name} → batch '{batch_dir.name}' (debouncing…)[/dim]"
                          if RICH else f"  Sprite file: {path.name}")
            self._schedule_batch(batch_dir)
        else:
            # Single file – check it's directly in watch_dir (not nested)
            try:
                rel = path.relative_to(self.watch_dir)
                if len(rel.parts) != 1:
                    return   # nested but not sprite-sheets → ignore
            except ValueError:
                return

            key = str(path)
            with self._lock:
                if key in self._seen_singles:
                    return
                self._seen_singles.add(key)

            # Short delay to ensure file is fully written
            def do_upload():
                time.sleep(0.5)
                upload_single_image(path, self.cfg)
                with self._lock:
                    self._seen_singles.discard(key)

            t = threading.Thread(target=do_upload, daemon=True)
            t.start()

# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse

    if not HAS_WATCHDOG:
        print("ERROR: watchdog not installed. Run: pip install watchdog")
        sys.exit(1)

    p = argparse.ArgumentParser(
        prog="watcher",
        description="Watch a folder and auto-upload images to Roblox Creator Store.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Folder layout:
  watch_dir/
  ├── icon.png                  ← uploaded immediately on creation
  └── sprite-sheets/
      └── PlayerRun/            ← subfolder name = universal batch name
          ├── frame_001.png     ← any prefix, number is extracted
          └── frame_002.png

Examples:
  python watcher.py --key KEY --user-id 123 --watch-dir ./assets
  python watcher.py --key KEY --user-id 123 --watch-dir ./assets --sprite-dir sprites \\
      --debounce 5 --webhook https://discord.com/api/webhooks/...
        """
    )

    auth = p.add_argument_group("Authentication")
    auth.add_argument("--key", default=os.environ.get("ROBLOX_API_KEY"),
                      help="Roblox Open Cloud API key (or ROBLOX_API_KEY env var)")
    creator = auth.add_mutually_exclusive_group()
    creator.add_argument("--user-id", metavar="ID", default=os.environ.get("USER_ID"),
                         help="User ID for upload (or set USER_ID env var)")
    creator.add_argument("--group-id", metavar="ID", default=os.environ.get("GROUP_ID"),
                         help="Group ID for upload (or set GROUP_ID env var)")

    watch = p.add_argument_group("Watch")
    watch.add_argument("--watch-dir", default=".", metavar="DIR",
                       help="Directory to watch (default: current dir)")
    watch.add_argument("--sprite-dir", default="sprite-sheets", metavar="NAME",
                       help="Subfolder name for sprite sheet batches (default: sprite-sheets)")
    watch.add_argument("--debounce", type=float, default=3.0, metavar="SECS",
                       help="Seconds to wait after last file change before processing a sprite batch (default: 3)")

    notif = p.add_argument_group("Notifications")
    notif.add_argument("--webhook", metavar="URL",
                       default=os.environ.get("DISCORD_WEBHOOK_URL"),
                       help="Discord webhook URL (or DISCORD_WEBHOOK_URL env var)")

    beh = p.add_argument_group("Upload Behaviour")
    beh.add_argument("--no-pixelfix", action="store_true")
    beh.add_argument("--no-dedup",    action="store_true")
    beh.add_argument("--distribute",  action="store_true")
    beh.add_argument("--dry-run",     action="store_true")
    beh.add_argument("--delay",       type=float, default=1.2, metavar="SECS",
                     help="Delay between uploads within a batch (default: 1.2)")

    args = p.parse_args()

    if not args.key:
        p.error("--key or ROBLOX_API_KEY required.")
    if not args.user_id and not args.group_id:
        p.error("Either --user-id or --group-id required.")

    watch_dir  = Path(args.watch_dir).resolve()
    sprite_dir = args.sprite_dir
    sprite_path = watch_dir / sprite_dir

    if not watch_dir.exists():
        print(f"ERROR: Watch dir does not exist: {watch_dir}")
        sys.exit(1)

    cfg = UploadConfig(
        api_key       = args.key,
        creator_type  = "user" if args.user_id else "group",
        creator_id    = args.user_id or args.group_id,
        skip_pixelfix = args.no_pixelfix,
        skip_dedup    = args.no_dedup,
        distribute    = args.distribute,
        dry_run       = args.dry_run,
        webhook_url   = args.webhook,
        upload_delay  = args.delay,
    )

    if RICH:
        console.print(Panel.fit(
            f"[bold]🔍 Roblox Watcher[/bold]\n\n"
            f"  [cyan]Watch dir:[/cyan]   {watch_dir}\n"
            f"  [cyan]Sprite dir:[/cyan]  {sprite_path}\n"
            f"  [cyan]Debounce:[/cyan]    {args.debounce}s\n"
            f"  [cyan]Creator:[/cyan]     {'user' if args.user_id else 'group'} {args.user_id or args.group_id}\n"
            f"  [cyan]Discord:[/cyan]     {'✓' if args.webhook else '✗'}\n"
            f"  [cyan]Pixelfix:[/cyan]    {'OFF' if args.no_pixelfix else 'ON'}\n"
            f"  [cyan]Dry run:[/cyan]     {'YES' if args.dry_run else 'NO'}",
            border_style="bright_blue"
        ))
    else:
        print(f"Watching: {watch_dir}  |  Sprite dir: {sprite_dir}  |  Discord: {'yes' if args.webhook else 'no'}")

    # Auto-create sprite-sheets dir if missing
    sprite_path.mkdir(parents=True, exist_ok=True)

    # Auto-download Pixelfix on Windows
    if not args.no_pixelfix and platform.system() == "Windows":
        download_pixelfix()

    handler  = RobloxWatchHandler(watch_dir, sprite_dir, cfg, args.debounce)
    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=True)
    observer.start()

    console.print("[green bold]✓ Watching for changes. Press Ctrl+C to stop.[/green bold]\n"
                  if RICH else "Watching... Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        console.print("\n[dim]Watcher stopped.[/dim]" if RICH else "\nStopped.")
    observer.join()

if __name__ == "__main__":
    main()
