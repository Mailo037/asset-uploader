#!/usr/bin/env python3
"""
Roblox Uploader - Watch Mode
Watches a folder for new images, handles sprite sheet batches,
uploads sequentially, and notifies via Discord webhook.

Usage:
  python watcher.py --key YOUR_KEY --user-id 12345 --watch-dir ./assets
"""

import os
import re
import sys
import json
import time
import threading
import platform
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Set
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    import urllib.request, urllib.parse

# Simplified output without rich tables to prevent Windows CMD crashes
def print_status(msg):
    print(msg)

sys.path.insert(0, str(Path(__file__).parent))
try:
    from uploader import (
        process_and_upload, load_history, save_history, file_hash,
        SUPPORTED_EXT, download_pixelfix,
    )
    UPLOADER_AVAILABLE = True
except ImportError as e:
    print(f"[ERROR] uploader.py not found or broken: {e}")
    sys.exit(1)

# -----------------------------------------------------------------------------
# Sprite sheet utilities
# -----------------------------------------------------------------------------

def extract_frame_number(filename: str) -> Optional[int]:
    stem = Path(filename).stem
    match = re.search(r"(\d+)\s*$", stem)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)", stem)
    return int(match.group(1)) if match else None

def normalize_sprite_name(universal_name: str, frame_number: int) -> str:
    return f"{universal_name} {frame_number}"

def sort_sprite_files(files: List[Path]) -> List[Tuple[int, Path]]:
    numbered = []
    unnumbered = []
    for f in files:
        n = extract_frame_number(f.name)
        if n is not None:
            numbered.append((n, f))
        else:
            unnumbered.append(f)

    numbered.sort(key=lambda x: x[0])

    if unnumbered:
        next_n = (numbered[-1][0] + 1) if numbered else 1
        for f in unnumbered:
            numbered.append((next_n, f))
            next_n += 1

    return numbered

# -----------------------------------------------------------------------------
# Discord Webhook
# -----------------------------------------------------------------------------

ROBLOX_ASSET_URL = "https://www.roblox.com/catalog/{asset_id}"

def discord_notify(
    webhook_url: str,
    batch_name: str,
    results: List[Dict],
    failed: List[Dict],
    batch_type: str = "single",
):
    if not webhook_url:
        return

    success_count = len([r for r in results if not r.get("dryRun") and r.get("assetId")])
    fail_count    = len(failed)
    color         = 0x00C853 if fail_count == 0 else (0xFF6D00 if success_count > 0 else 0xD50000)

    fields = []
    ticks = chr(96) * 3

    if batch_type == "sprite_sheet":
        id_lines = []
        for r in results:
            aid = r.get("assetId", "?")
            frame = r.get("frame", "?")
            url   = ROBLOX_ASSET_URL.format(asset_id=aid) if aid != "?" else None
            line  = f"`{frame}` -> [{aid}]({url})" if url else f"`{frame}` -> `{aid}`"
            id_lines.append(line)

        chunk_size = 10
        for i in range(0, len(id_lines), chunk_size):
            chunk = id_lines[i:i + chunk_size]
            fields.append({
                "name": f"Asset IDs (frames {i+1}-{min(i+chunk_size, len(id_lines))})",
                "value": "\n".join(chunk),
                "inline": False,
            })

        ids_array = ", ".join(str(r.get("assetId", 0)) for r in results)
        lua_snippet = f"local {batch_name.replace(' ', '')}IDs = {{ {ids_array} }}"
        fields.append({
            "name": "[LUA] Lua Snippet",
            "value": f"{ticks}lua\n{lua_snippet[:900]}\n{ticks}",
            "inline": False,
        })
    else:
        lines = []
        for r in results:
            aid  = r.get("assetId", "?")
            name = r.get("name", Path(r.get("file", "?")).name)
            url  = ROBLOX_ASSET_URL.format(asset_id=aid) if aid != "?" else None
            lines.append(f"**{name}** -> [{aid}]({url})" if url else f"**{name}** -> `{aid}`")
        if lines:
            fields.append({"name": "Uploaded Assets", "value": "\n".join(lines[:20]), "inline": False})

    if failed:
        fail_lines = [f"[X] `{Path(f['file']).name}`: {f['error'][:80]}" for f in failed[:5]]
        fields.append({"name": "Failures", "value": "\n".join(fail_lines), "inline": False})

    embed = {
        "title": f"{'[BATCH] Sprite Sheet' if batch_type == 'sprite_sheet' else '[IMG] Upload'}: **{batch_name}**",
        "color": color,
        "fields": fields,
        "footer": {"text": f"Roblox Uploader - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    stats_parts = [f"[OK] {success_count} uploaded"]
    if fail_count:
        stats_parts.append(f"[X] {fail_count} failed")
    if batch_type == "sprite_sheet":
        stats_parts.append(f"[FRAME] {len(results)} frames")
    embed["description"] = "  -  ".join(stats_parts)

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
        print("  [MAIL] Discord notified.")
    except Exception as e:
        print(f"  [WARN] Discord webhook failed: {e}")

# -----------------------------------------------------------------------------
# Batch processor
# -----------------------------------------------------------------------------

class UploadConfig:
    def __init__(self, api_key, creator_type, creator_id, skip_pixelfix,
                 skip_dedup, distribute, dry_run, webhook_url, upload_delay, asset_type):
        self.api_key       = api_key
        self.creator_type  = creator_type
        self.creator_id    = creator_id
        self.skip_pixelfix = skip_pixelfix
        self.skip_dedup    = skip_dedup
        self.distribute    = distribute
        self.dry_run       = dry_run
        self.webhook_url   = webhook_url
        self.upload_delay  = upload_delay
        self.asset_type    = asset_type

def upload_single_image(path: Path, cfg: UploadConfig) -> Optional[Dict]:
    print(f"\n[IMG] Single upload: {path.name}")
    try:
        record = process_and_upload(
            image_path   = path,
            api_key      = cfg.api_key,
            creator_type = cfg.creator_type,
            creator_id   = cfg.creator_id,
            display_name = None,
            description  = "Uploaded by Roblox Watcher",
            skip_pixelfix= cfg.skip_pixelfix,
            skip_dedup   = cfg.skip_dedup,
            distribute   = cfg.distribute,
            dry_run      = cfg.dry_run,
            asset_type   = cfg.asset_type,
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
        print(f"  [ERROR] {e}")
        if cfg.webhook_url:
            discord_notify(cfg.webhook_url, path.stem, [], [{"file": str(path), "error": str(e)}], "single")
        return None

def upload_sprite_batch(batch_dir: Path, universal_name: str, cfg: UploadConfig):
    print(f"\n[BATCH] Sprite batch: {universal_name} ({batch_dir})")

    raw_files = [
        f for f in batch_dir.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXT
    ]
    if not raw_files:
        print("  [WARN] No files found in batch dir.")
        return

    sorted_frames = sort_sprite_files(raw_files)
    print(f"  {len(sorted_frames)} frames detected.")

    results = []
    failed  = []

    for i, (frame_num, file_path) in enumerate(sorted_frames):
        display_name = normalize_sprite_name(universal_name, frame_num)
        print(f"  [{i+1}/{len(sorted_frames)}] {file_path.name} -> {display_name}")

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
                asset_type   = cfg.asset_type,
            )
            if record:
                record["frame"] = frame_num
                record["name"]  = display_name
                results.append(record)
        except Exception as e:
            print(f"    [ERROR] {e}")
            failed.append({"file": str(file_path), "frame": frame_num, "error": str(e)})

        if i < len(sorted_frames) - 1:
            time.sleep(cfg.upload_delay)

    # Simple ASCII summary output (safe for Windows CMD)
    print(f"\n{'='*50}")
    print(f"ASSET IDs FOR: {universal_name}")
    print(f"{'='*50}")
    for r in results:
        aid = str(r.get("assetId", "DRY RUN"))
        print(f"  Frame {r['frame']:>3} | {aid:<15} | {r['name']}")
    print(f"{'='*50}")

    if cfg.webhook_url:
        discord_notify(cfg.webhook_url, universal_name, results, failed, "sprite_sheet")

# -----------------------------------------------------------------------------
# Watch handler (watchdog)
# -----------------------------------------------------------------------------

class RobloxWatchHandler(FileSystemEventHandler):
    def __init__(self, watch_dir: Path, sprite_dir: str, cfg: UploadConfig, debounce_secs: float = 3.0):
        super().__init__()
        self.watch_dir     = watch_dir.resolve()
        self.sprite_dir    = sprite_dir
        self.cfg           = cfg
        self.debounce_secs = debounce_secs

        self._timers: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()
        self._seen_singles: Set[str] = set()

    def _is_sprite_file(self, path: Path) -> Optional[Path]:
        try:
            rel = path.relative_to(self.watch_dir / self.sprite_dir)
            parts = rel.parts
            if len(parts) == 2:
                return self.watch_dir / self.sprite_dir / parts[0]
        except ValueError:
            pass
        return None

    def _schedule_batch(self, batch_dir: Path):
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
        with self._lock:
            self._timers.pop(str(batch_dir), None)
        universal_name = batch_dir.name
        upload_sprite_batch(batch_dir, universal_name, self.cfg)

    def on_created(self, event):
        if event.is_directory: return
        self._handle(Path(event.src_path))

    def on_modified(self, event):
        if event.is_directory: return
        self._handle(Path(event.src_path))

    def on_moved(self, event):
        if event.is_directory: return
        self._handle(Path(event.dest_path))

    def _handle(self, path: Path):
        path = path.resolve()
        if path.suffix.lower() not in SUPPORTED_EXT:
            return

        batch_dir = self._is_sprite_file(path)
        if batch_dir:
            print(f"  [DIR] Sprite file detected: {path.name} -> batch '{batch_dir.name}' (debouncing...)")
            self._schedule_batch(batch_dir)
        else:
            try:
                rel = path.relative_to(self.watch_dir)
                if len(rel.parts) != 1: return
            except ValueError:
                return

            key = str(path)
            with self._lock:
                if key in self._seen_singles: return
                self._seen_singles.add(key)

            def do_upload():
                time.sleep(0.5)
                upload_single_image(path, self.cfg)
                with self._lock:
                    self._seen_singles.discard(key)

            t = threading.Thread(target=do_upload, daemon=True)
            t.start()

# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main():
    import argparse

    if not HAS_WATCHDOG:
        print("[ERROR] watchdog not installed. Run: pip install watchdog")
        sys.exit(1)

    p = argparse.ArgumentParser(prog="watcher")
    auth = p.add_argument_group("Authentication")
    auth.add_argument("--key", default=os.environ.get("ROBLOX_API_KEY"))
    creator = auth.add_mutually_exclusive_group()
    creator.add_argument("--user-id", default=os.environ.get("USER_ID"))
    creator.add_argument("--group-id", default=os.environ.get("GROUP_ID"))

    watch = p.add_argument_group("Watch")
    watch.add_argument("--watch-dir", default=".")
    watch.add_argument("--sprite-dir", default="sprite-sheets")
    watch.add_argument("--debounce", type=float, default=3.0)

    notif = p.add_argument_group("Notifications")
    notif.add_argument("--webhook", default=os.environ.get("DISCORD_WEBHOOK_URL"))

    beh = p.add_argument_group("Upload Behaviour")
    beh.add_argument("--no-pixelfix", action="store_true")
    beh.add_argument("--no-dedup",    action="store_true")
    beh.add_argument("--distribute",  action="store_true")
    beh.add_argument("--dry-run",     action="store_true")
    beh.add_argument("--asset-type",  default="Decal")
    beh.add_argument("--delay",       type=float, default=1.2)

    args = p.parse_args()

    if not args.key: p.error("--key or ROBLOX_API_KEY required.")
    if not args.user_id and not args.group_id: p.error("Either --user-id or --group-id required.")

    watch_dir  = Path(args.watch_dir).resolve()
    sprite_dir = args.sprite_dir
    sprite_path = watch_dir / sprite_dir

    if not watch_dir.exists():
        print(f"[ERROR] Watch dir does not exist: {watch_dir}")
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
        asset_type    = args.asset_type,
    )

    print("\n============================================================")
    print("[WATCHER] ROBLOX WATCHER STARTED")
    print("============================================================")
    print(f"Watch dir:  {watch_dir}")
    print(f"Sprite dir: {sprite_path}")
    print(f"Creator:    {'user' if args.user_id else 'group'} {args.user_id or args.group_id}")
    print(f"Asset Type: {args.asset_type}")
    print(f"Discord:    {'[OK]' if args.webhook else '[X]'}")
    print(f"Pixelfix:   {'[OFF]' if args.no_pixelfix else '[ON]'}")
    print(f"Dry run:    {'[YES]' if args.dry_run else '[NO]'}")
    print("============================================================\n")

    sprite_path.mkdir(parents=True, exist_ok=True)

    if not args.no_pixelfix and platform.system() == "Windows":
        download_pixelfix()

    handler  = RobloxWatchHandler(watch_dir, sprite_dir, cfg, args.debounce)
    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=True)
    observer.start()

    print("[OK] Watching for changes. Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\n[INFO] Watcher stopped.")
    observer.join()

if __name__ == "__main__":
    main()