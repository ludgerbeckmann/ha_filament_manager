"""Render the Filament Manager brand icon (spool with an unwinding filament).

Usage (needs Pillow):  python tools/render_icon.py

Writes icon.png (256 px) and icon@2x.png (512 px), transparent background, to
brand/ and custom_components/ha_filament_manager/brand/.

The spool is drawn at 4x and scaled down for clean edges. Its measurements
(512 px canvas, centre 256/256) match the original artwork: flange r=235.75,
dark ring up to r=177, winding disk r=171.6 with three darker winding lines,
centre hole r=48.75.

The filament leaves the outermost winding line tangentially (so it looks like
it comes straight out of the winding, not attached to it) and unwinds in a
bend whose radius grows from the winding's own radius to FILAMENT_END_RADIUS.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

SS = 4  # supersampling factor
SIZE = 512
CENTER = SIZE / 2

FLANGE = (120, 120, 122, 255)
RING = (67, 67, 69, 255)
ORANGE = (255, 112, 67, 255)
WINDING_LINE = (229, 73, 24, 255)

# Filament geometry (screen coordinates, angles in degrees, 0 = right, -90 = top).
EXIT_ANGLE = -75  # where it leaves the winding: about half past twelve / one o'clock
EXIT_RADIUS = 152  # on the outermost winding line
FILAMENT_END_RADIUS = 500  # bend radius at the free end (starts at EXIT_RADIUS)
FILAMENT_LENGTH = 460
FILAMENT_WIDTH = 12


def _circle(draw: ImageDraw.ImageDraw, radius: float, fill: tuple[int, ...]) -> None:
    c = CENTER * SS
    r = radius * SS
    draw.ellipse([c - r, c - r, c + r, c + r], fill=fill)


def _filament_points(step: float = 0.5) -> list[tuple[float, float]]:
    angle = math.radians(EXIT_ANGLE)
    x = CENTER + EXIT_RADIUS * math.cos(angle)
    y = CENTER + EXIT_RADIUS * math.sin(angle)
    heading = angle + math.pi / 2  # tangent to the winding, clockwise
    points = [(x, y)]
    steps = int(FILAMENT_LENGTH / step)
    for i in range(steps):
        radius = EXIT_RADIUS + (FILAMENT_END_RADIUS - EXIT_RADIUS) * i / steps
        x += math.cos(heading) * step
        y += math.sin(heading) * step
        heading += step / radius  # clockwise bend, flattening out
        points.append((x, y))
    return points


def render() -> Image.Image:
    """Return the icon at SIZE*SS pixels."""
    image = Image.new("RGBA", (SIZE * SS, SIZE * SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    _circle(draw, 235.75, FLANGE)
    _circle(draw, 177, RING)
    _circle(draw, 171.6, ORANGE)
    for radius in (151.5, 121.5, 90.5):  # outermost first, so the inner lines stay visible
        _circle(draw, radius + 1.75, WINDING_LINE)
        _circle(draw, radius - 1.75, ORANGE)

    # Filament: round dots along the path give smooth edges and round ends.
    half = FILAMENT_WIDTH * SS / 2
    for x, y in _filament_points():
        draw.ellipse([x * SS - half, y * SS - half, x * SS + half, y * SS + half], fill=ORANGE)

    # Punch the centre hole.
    hole = Image.new("L", image.size, 255)
    c, r = CENTER * SS, 48.75 * SS
    ImageDraw.Draw(hole).ellipse([c - r, c - r, c + r, c + r], fill=0)
    image.putalpha(ImageChops.multiply(image.getchannel("A"), hole))
    return image


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    big = render()
    outputs = {"icon@2x.png": 512, "icon.png": 256}
    for folder in (root / "brand", root / "custom_components" / "ha_filament_manager" / "brand"):
        folder.mkdir(parents=True, exist_ok=True)
        for name, size in outputs.items():
            big.resize((size, size), Image.LANCZOS).save(folder / name, optimize=True)
            print("wrote", (folder / name).relative_to(root))


if __name__ == "__main__":
    main()
