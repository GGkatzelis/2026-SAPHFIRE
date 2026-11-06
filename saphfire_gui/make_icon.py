"""Make the window icon and the logo from the SAPHIR biomass-burning photo.

    python make_icon.py                # uses "../SAPHIR Biomass Burning.jpg"
    python make_icon.py other.jpg

Writes next to this file:
    SAPHFIRE Logo.png   256 px, shown in the loading box
    SAPHFIRE.ico        16 to 256 px, window and taskbar icon

The large sizes show the fire, its smoke and the chamber; the small sizes (up to 48 px) use a
tighter crop so the fire is still recognisable. Change the crop boxes below to reframe.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "SAPHIR Biomass Burning.jpg"
WIDE = (150, 165, 750, 765)        # left, top, right, bottom in the 1024 x 765 photo
TIGHT = (200, 265, 700, 765)
LARGE, SMALL = (256, 128, 64), (48, 32, 24, 16)


def rounded(square: Image.Image, size: int) -> Image.Image:
    """Resize to ``size`` and round the corners (transparent outside)."""
    im = square.resize((size, size), Image.LANCZOS).convert("RGBA")
    scale = 4                                                    # draw the mask larger for a smooth edge
    mask = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size * scale - 1, size * scale - 1), radius=int(0.18 * size * scale), fill=255)
    im.putalpha(mask.resize((size, size), Image.LANCZOS))
    return im


def main(source: Path = SOURCE) -> None:
    photo = Image.open(source).convert("RGB")
    wide, tight = photo.crop(WIDE), photo.crop(TIGHT)
    rounded(wide, 256).save(HERE / "SAPHFIRE Logo.png")
    images = [rounded(wide, s) for s in LARGE] + [rounded(tight, s) for s in SMALL]      # one drawn image per size
    images[0].save(HERE / "SAPHFIRE.ico", format="ICO", sizes=[(s, s) for s in LARGE + SMALL],
                   append_images=images[1:])
    print(f"written: {HERE / 'SAPHFIRE Logo.png'} and SAPHFIRE.ico")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE)
