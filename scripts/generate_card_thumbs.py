"""Generate small WebP thumbnails for every card art PNG.

Card art originals are 1024x1024 PNGs (1.5-3 MB each); the in-game UI
renders them at ~280x420. Decoding multi-megapixel images for tiny
tiles is the main cause of perceived "image lag" during slam-in
animations and renders. This script writes a sibling
`<card_id>.thumb.webp` (~50 KB each) that the in-game JS renderers
load instead. The full PNG stays for tooltip lazy-loading.

Re-run any time card art is added or replaced. Idempotent.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ART_DIR = Path(__file__).resolve().parents[1] / "src" / "grid_tactics" / "server" / "static" / "art"
THUMB_MAX = 512
WEBP_QUALITY = 82


def main() -> None:
    pngs = sorted(p for p in ART_DIR.iterdir() if p.suffix.lower() == ".png")
    total_in = 0
    total_out = 0
    skipped = 0
    written = 0
    for src in pngs:
        dst = src.with_suffix(".thumb.webp")
        src_size = src.stat().st_size
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            total_in += src_size
            total_out += dst.stat().st_size
            skipped += 1
            continue
        with Image.open(src) as im:
            im = im.convert("RGB") if im.mode != "RGB" else im
            im.thumbnail((THUMB_MAX, THUMB_MAX), Image.Resampling.LANCZOS)
            im.save(dst, "WEBP", quality=WEBP_QUALITY, method=6)
        total_in += src_size
        total_out += dst.stat().st_size
        written += 1
        print(f"  {src.name:40s} {src_size/1024:6.0f} KB  ->  {dst.name:45s} {dst.stat().st_size/1024:5.0f} KB")
    print()
    print(f"Wrote {written} thumbnails, skipped {skipped} up-to-date.")
    print(f"Originals: {total_in/1024/1024:.1f} MB    Thumbnails: {total_out/1024/1024:.1f} MB    Saving: {(1 - total_out/total_in)*100:.0f}%")


if __name__ == "__main__":
    main()
