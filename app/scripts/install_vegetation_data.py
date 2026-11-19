"""Verify and install the bundled tree-height and green-area runtime data offline."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


APP_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ROOT = APP_ROOT.parent / "data" / "vegetation"


def data_root(configured: str | None = None) -> Path:
    selected = configured or os.environ.get("UAV_DATA_DIR")
    if selected:
        return Path(selected).expanduser().resolve()
    marker = APP_ROOT / "deployment-layout.json"
    if marker.is_file():
        layout = json.loads(marker.read_text(encoding="utf-8"))
        return (APP_ROOT / layout["data_directory"]).resolve()
    return APP_ROOT


def safe_path(root: Path, relative: str) -> Path:
    parts = relative.split("/")
    if (not parts or parts[0] not in {"measurement_data", "prelabel_output", "models"}
            or any(not part or part in {".", ".."} or "\\" in part or ":" in part
                   or part.endswith((".", " ")) for part in parts)):
        raise ValueError(f"Invalid manifest path: {relative!r}")
    current = root
    for part in [None, *parts]:
        if part is not None:
            current = current / part
        try:
            # Covers symlinks and Windows junctions, including dangling links.
            info = current.lstat()
        except FileNotFoundError:
            continue
        if current.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Refusing linked data path: {current}")
    return current


def matches(path: Path, entry: dict) -> bool:
    if not path.is_file() or path.stat().st_size != entry["bytes"]:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest() == entry["sha256"]


def verify_bundle(bundle: Path) -> list[dict]:
    manifest_path = bundle / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Refusing linked manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or not isinstance(manifest.get("files"), list):
        raise ValueError("Unsupported vegetation manifest")
    entries = manifest["files"]
    seen = set()
    for entry in entries:
        if (not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
                or type(entry.get("bytes")) is not int or entry["bytes"] < 0
                or not isinstance(entry.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None):
            raise ValueError("Invalid vegetation manifest entry")
        name = entry["path"].casefold()
        if name in seen:
            raise ValueError(f"Duplicate manifest path: {entry['path']}")
        seen.add(name)
        source = safe_path(bundle, entry["path"])
        if not matches(source, entry):
            raise ValueError(f"Source size or SHA-256 mismatch: {entry['path']}")
    if not entries or manifest.get("total_bytes") != sum(item["bytes"] for item in entries):
        raise ValueError("Invalid vegetation manifest total")
    return entries


def install(root: Path, bundle: Path = BUNDLE_ROOT, overwrite: bool = False) -> dict[str, int]:
    entries = verify_bundle(bundle)
    pending_entries = []
    skipped = 0
    # Check every existing destination before copying any file.
    for entry in entries:
        target = safe_path(root, entry["path"])
        if target.exists():
            if matches(target, entry):
                skipped += 1
                continue
            if not target.is_file() or not overwrite:
                raise ValueError(f"Existing data differs: {target}; back up before using --overwrite")
        pending_entries.append(entry)

    for entry in pending_entries:
        source = safe_path(bundle, entry["path"])
        target = safe_path(root, entry["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        pending = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".vegetation-", suffix=".tmp", delete=False) as stream:
                pending = Path(stream.name)
                with source.open("rb") as input_stream:
                    shutil.copyfileobj(input_stream, stream, 1024 * 1024)
            if not matches(pending, entry):
                raise ValueError(f"Copied data failed SHA-256 verification: {entry['path']}")
            safe_path(root, entry["path"])
            if overwrite:
                os.replace(pending, target)
            else:
                # Exclusive publication also protects an upload created after preflight.
                os.link(pending, target)
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)
    return {"installed": len(pending_entries), "skipped": skipped, "files": len(entries)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", help="Use the same data root as the server's UAV_DATA_DIR")
    parser.add_argument("--bundle", "--bundle-dir", dest="bundle_dir", type=Path, default=BUNDLE_ROOT,
                        help="Local data bundle directory")
    parser.add_argument("--verify-only", action="store_true", help="Verify the bundle without installing")
    parser.add_argument("--overwrite", action="store_true", help="Replace different existing files after verification")
    args = parser.parse_args()
    try:
        if args.verify_only:
            entries = verify_bundle(args.bundle_dir)
            print(f"Verified {len(entries)} files ({sum(item['bytes'] for item in entries):,} bytes).")
        else:
            root = data_root(args.data_dir)
            result = install(root, args.bundle_dir, args.overwrite)
            print(f"Vegetation data ready: {root} (installed={result['installed']}, unchanged={result['skipped']})")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Installation failed: {exc}\n")


if __name__ == "__main__":
    main()
