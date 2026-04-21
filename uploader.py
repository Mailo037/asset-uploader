#!/usr/bin/env python3
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
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Set
import mimetypes
from dotenv import load_dotenv

load_dotenv()

# -- Optional rich output ------------------------------------------------------
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.markup import escape
    from rich import print as rprint
    RICH = True
    console = Console()
except ImportError:
    RICH = False
    def escape(text): return str(text)
    class Console:
        def print(self, *a, **kw): print(*a)
        def log(self, *a, **kw): print("[LOG]", *a)
    console = Console()
    def rprint(*a, **kw): print(*a)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    import urllib.request as urlreq

# -- Optional Pillow for Metadata Extraction -----------------------------------
try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

# -- Constants -----------------------------------------------------------------
PIXELFIX_URL = "https://github.com/Corecii/Transparent-Pixel-Fix/releases/download/1.0.0/pixelfix-win-x64.exe"
PIXELFIX_BIN = Path(__file__).parent / "tools" / "pixelfix-win-x64.exe"
ROBLOX_ASSETS_API = "https://apis.roblox.com/assets/v1/assets"
ROBLOX_OPS_API    = "https://apis.roblox.com/assets/v1/operations/{op_id}"
HISTORY_FILE      = Path(__file__).parent / "upload_history.json"
SUPPORTED_EXT     = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".mp3", ".ogg", ".wav", ".fbx", ".obj"}
RATE_LIMIT_DELAY  = 1.2   # seconds between uploads (stay under Roblox limits)
MAX_POLL_ATTEMPTS = 30
POLL_INTERVAL     = 2.0   # seconds between operation polls

# -- History (deduplication) ---------------------------------------------------
def load_history() -> Dict:
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {}

def save_history(history: Dict):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

# -- Metadata Extraction -------------------------------------------------------
def get_image_comment(image_path: Path) -> Optional[str]:
    """
    Attempts to extract metadata comments or descriptions from the image.
    Works for PNG chunks and JPG EXIF data.
    """
    if not HAS_PILLOW or image_path.suffix.lower() not in {'.png', '.jpg', '.jpeg'}:
        return None
        
    try:
        with Image.open(image_path) as img:
            # 1. Try PNG Text Infos (tEXt, iTXt, zTXt chunks)
            if hasattr(img, 'text') and img.text:
                for key in ['Comment', 'Description', 'Title', 'UserComment']:
                    if key in img.text:
                        return str(img.text[key]).strip()
            
            if 'Comment' in img.info:
                return str(img.info['Comment']).strip()
            if 'Description' in img.info:
                return str(img.info['Description']).strip()

            # 2. Try JPG EXIF Data
            exif = img.getexif()
            if exif:
                # 37510 = UserComment, 270 = ImageDescription
                for tag_id in [37510, 270]:
                    val = exif.get(tag_id)
                    if val:
                        # Clean up EXIF-Prefixes (like ASCII\0\0\0)
                        if isinstance(val, bytes):
                            val = val.decode('utf-8', errors='ignore')
                        val_str = str(val).replace('ASCII\x00\x00\x00', '').replace('\x00', '').strip()
                        if val_str:
                            return val_str
    except Exception as e:
        print(f"  [WARN] Could not read metadata from {image_path.name}: {e}")
        
    return None

# -- Pixelfix ------------------------------------------------------------------
def download_pixelfix():
    """Download Pixelfix binary if not present (Windows only)."""
    if platform.system() != "Windows":
        return False
    if PIXELFIX_BIN.exists():
        return True
    
    print("Downloading Pixelfix...")
    PIXELFIX_BIN.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(PIXELFIX_URL, PIXELFIX_BIN)
        print("[OK] Pixelfix downloaded successfully.")
        return True
    except Exception as e:
        print(f"[ERROR] Could not download Pixelfix: {e}")
        return False

def run_pixelfix(image_path: Path, output_path: Optional[Path] = None) -> Path:
    if platform.system() != "Windows":
        print(f"  [SKIP] Pixelfix is Windows-only. Skipping for {image_path.name}")
        return image_path

    if not PIXELFIX_BIN.exists():
        if not download_pixelfix():
            print(f"  [WARN] Pixelfix unavailable. Uploading original.")
            return image_path

    if output_path is None:
        output_path = image_path.parent / "pixelfix_out" / image_path.name
    
    # Ensure the output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Copy the original file to the output path to prevent overwriting the original file
    try:
        shutil.copy2(image_path, output_path)
    except Exception as e:
        print(f"  [ERROR] Could not copy file for Pixelfix: {e}")
        return image_path

    # 2. Run Pixelfix ONLY on the copied file (Pixelfix overwrites files in-place)
    result = subprocess.run(
        [str(PIXELFIX_BIN), str(output_path)],
        capture_output=True, text=True
    )
    
    # SAFETY CHECK: Did Pixelfix actually succeed?
    if result.returncode != 0 or not output_path.exists():
        print(f"  [WARN] Pixelfix failed on {image_path.name}. Uploading original file instead.")
        # Clean up the corrupted copy if it exists
        if output_path.exists():
            output_path.unlink()
        return image_path

    return output_path

# -- Roblox API ----------------------------------------------------------------
def make_headers(api_key: str) -> Dict:
    return {"x-api-key": api_key}

def upload_asset(
    api_key: str,
    image_path: Path,
    display_name: str,
    description: str,
    creator_type: str,   # "user" or "group"
    creator_id: str,
    asset_type: str = "Decal",
) -> Dict:
    mime = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
    
    if mime == "application/octet-stream" and image_path.suffix.lower() in {".fbx", ".obj"}:
        mime = "model/" + image_path.suffix.lower()[1:]

    request_body = {
        "assetType": asset_type,
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
        import io, email.generator
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

def poll_operation(api_key: str, operation_path: str) -> Optional[Dict]:
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
    url = f"https://apis.roblox.com/assets/v1/assets/{asset_id}"
    payload = {"previews": []}
    if HAS_REQUESTS:
        resp = requests.patch(
            url,
            headers={**make_headers(api_key), "Content-Type": "application/json"},
            json=payload
        )
        if resp.status_code not in (200, 204):
            print(f"[INFO] Creator Store needs manual setup (HTTP {resp.status_code})")

# -- Manifest loading ----------------------------------------------------------
def load_manifest(manifest_path: Path) -> List[Dict]:
    with open(manifest_path) as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("assets", [])

# -- Core upload logic ---------------------------------------------------------
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
    asset_type: str = "Decal",
) -> Optional[Dict]:

    history = load_history()

    if not skip_dedup:
        h = file_hash(image_path)
        if h in history:
            prev = history[h]
            print(f"  [SKIP] {image_path.name} (already uploaded as assetId={prev['assetId']})")
            return prev

    name = display_name or image_path.stem.replace("_", " ").replace("-", " ").title()

    # --- Fetch Metadata Comment ---
    extracted_comment = get_image_comment(image_path)
    if extracted_comment:
        description = extracted_comment
        print(f"  [INFO] Found metadata comment: '{description}'")

    processed = image_path
    if not skip_pixelfix and image_path.suffix.lower() == ".png":
        print(f"  -> Running Pixelfix...")
        processed = run_pixelfix(image_path)

    if dry_run:
        print(f"  [DRY RUN] Would upload '{name}' from {processed}")
        return {"dryRun": True, "file": str(image_path), "name": name}

    print(f"  -> Uploading '{name}' as {asset_type}...")
    op = upload_asset(api_key, processed, name, description, creator_type, creator_id, asset_type)

    op_path = op.get("path") or op.get("operationId")
    if op_path:
        print(f"  -> Polling operation...")
        result = poll_operation(api_key, op_path)
    else:
        result = op

    asset_id = (
        result.get("assetId")
        or result.get("assetVersionId") 
        or result.get("id")
    )
    if not asset_id:
        print(f"  [WARN] No assetId in response")

    if distribute and asset_id:
        print("  -> Configuring Creator Store...")
        set_creator_store_free(api_key, str(asset_id))

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

    print(f"  [OK] Done -> assetId={asset_id}")
    return record

# -- CLI -----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="roblox_uploader",
        description="Upload assets to the Roblox Creator Store with Pixelfix preprocessing.",
    )
    auth = p.add_argument_group("Authentication")
    auth.add_argument("--key", metavar="API_KEY", default=os.environ.get("ROBLOX_API_KEY"))
    creator = auth.add_mutually_exclusive_group()
    creator.add_argument("--user-id", metavar="ID", default=os.environ.get("USER_ID"))
    creator.add_argument("--group-id", metavar="ID", default=os.environ.get("GROUP_ID"))

    inp = p.add_argument_group("Input")
    inp.add_argument("input", nargs="*")
    inp.add_argument("--manifest", metavar="FILE")

    meta = p.add_argument_group("Metadata")
    meta.add_argument("--asset-type", default="Decal")
    meta.add_argument("--name", metavar="NAME")
    meta.add_argument("--description", metavar="TEXT", default="Uploaded by roblox_uploader")

    beh = p.add_argument_group("Behaviour")
    beh.add_argument("--no-pixelfix", action="store_true")
    beh.add_argument("--no-dedup", action="store_true")
    beh.add_argument("--distribute", action="store_true")
    beh.add_argument("--dry-run", action="store_true")
    beh.add_argument("--delay", type=float, default=RATE_LIMIT_DELAY)

    out = p.add_argument_group("Output")
    out.add_argument("--results", metavar="FILE")

    return p

def collect_images(inputs: List[str]) -> List[Path]:
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
            print(f"[WARN] Skipping unsupported input: {inp}")
            
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

    if not args.key:
        parser.error("--key or ROBLOX_API_KEY env var required.")
    if not args.user_id and not args.group_id:
        parser.error("Either --user-id or --group-id is required.")
    if not args.input and not args.manifest:
        parser.error("Provide at least one input file/folder or --manifest.")

    creator_type = "user" if args.user_id else "group"
    creator_id   = args.user_id or args.group_id

    print("\n============================================================")
    print("ROBLOX CREATOR STORE UPLOADER")
    print("============================================================")
    print(f"Creator: {creator_type} {creator_id} | Type: {args.asset_type}")
    print(f"Pixelfix: {'OFF' if args.no_pixelfix else 'ON'} | Dry run: {'YES' if args.dry_run else 'NO'}")
    print(f"Metadata Extract: {'[ON]' if HAS_PILLOW else '[OFF] (pip install Pillow for metadata support)'}")
    print("============================================================\n")

    tasks: List[Dict] = []

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
            print("[ERROR] No supported files found.")
            sys.exit(1)
        for img in images:
            tasks.append({
                "path": img,
                "name": args.name if len(images) == 1 else None,
                "description": args.description,
            })

    print(f"{len(tasks)} file(s) queued.\n")

    if not args.no_pixelfix and platform.system() == "Windows":
        download_pixelfix()

    results = []
    failed  = []

    for i, task in enumerate(tasks, 1):
        path = task["path"]
        print(f"[{i}/{len(tasks)}] {path.name}")

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
                asset_type   = args.asset_type,
            )
            if record:
                results.append(record)
        except Exception as e:
            print(f"  [ERROR] {e}")
            failed.append({"file": str(path), "error": str(e)})

        if i < len(tasks):
            time.sleep(args.delay)

    print(f"\n{'='*60}")
    print("UPLOAD SUMMARY")
    print(f"{'='*60}")
    
    for r in results:
        status = "[DRY RUN]" if r.get("dryRun") else "[OK]"
        asset_id = str(r.get("assetId", "-"))
        filename = Path(r.get("file", "?")).name
        print(f"{status} | {asset_id:<15} | {filename}")
        
    for f in failed:
        filename = Path(f["file"]).name
        print(f"[FAILED] | {'-':<15} | {filename} ({f['error'][:40]})")
        
    print(f"{'='*60}")
    print(f"Done: {len(results)} uploaded, {len(failed)} failed.")

    if args.results:
        out = {"uploaded": results, "failed": failed}
        with open(args.results, "w") as f:
            json.dump(out, f, indent=2)
        print(f"Results written to -> {args.results}")

    if failed:
        sys.exit(1)

if __name__ == "__main__":
    main()