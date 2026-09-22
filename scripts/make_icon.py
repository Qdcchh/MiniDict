"""Render the MiniDict app icon (blue rounded square with 译) into an .icns."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


SIZE = 1024
ICONSET_SIZES = (16, 32, 128, 256, 512)


def render_png(path: Path) -> None:
    from AppKit import (
        NSAttributedString,
        NSBezierPath,
        NSColor,
        NSFont,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSImage,
    )

    image = NSImage.alloc().initWithSize_((SIZE, SIZE))
    image.lockFocus()
    # PyObjC depythonifies NSRect/NSPoint from the Foundation helpers, not tuples.
    from Foundation import NSMakePoint, NSMakeRect

    background = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(0, 0, SIZE, SIZE), 230, 230
    )
    NSColor.colorWithCalibratedRed_green_blue_alpha_(
        0.16, 0.47, 0.92, 1.0
    ).setFill()
    background.fill()
    label = NSAttributedString.alloc().initWithString_attributes_(
        "译",
        {
            NSFontAttributeName: NSFont.boldSystemFontOfSize_(560),
            NSForegroundColorAttributeName: NSColor.whiteColor(),
        },
    )
    extent = label.size()
    label.drawAtPoint_(
        NSMakePoint((SIZE - extent.width) / 2, (SIZE - extent.height) / 2)
    )
    image.unlockFocus()

    # Write TIFF and let sips make the PNG: fewer PyObjC bitmap APIs to depend on.
    tiff = path.with_suffix(".tiff")
    if not image.TIFFRepresentation().writeToFile_atomically_(str(tiff), True):
        raise RuntimeError(f"could not write {tiff}")
    subprocess.run(
        ["sips", "-s", "format", "png", str(tiff), "--out", str(path)],
        check=True,
    )
    tiff.unlink()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: make_icon.py OUTPUT.icns")
    destination = Path(sys.argv[1])
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as work:
        workdir = Path(work)
        png = workdir / "icon.png"
        render_png(png)
        iconset = workdir / "MiniDict.iconset"
        iconset.mkdir()
        for size in ICONSET_SIZES:
            subprocess.run(
                ["sips", "-z", str(size), str(size), str(png),
                 "--out", str(iconset / f"icon_{size}x{size}.png")],
                check=True,
            )
            subprocess.run(
                ["sips", "-z", str(size * 2), str(size * 2), str(png),
                 "--out", str(iconset / f"icon_{size}x{size}@2x.png")],
                check=True,
            )
        subprocess.run(
            ["iconutil", "-c", "icns", "-o", str(destination), str(iconset)],
            check=True,
        )
    print(f"wrote {destination}")


if __name__ == "__main__":
    main()
