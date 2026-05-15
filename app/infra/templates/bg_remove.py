"""
Product photo background removal using Pillow.

Detects the dominant background color from the edges of the image,
then makes all similar-colored pixels transparent. No AI needed —
works for product photos on solid white/gray/light backgrounds.

Returns PNG bytes with alpha channel.
"""

from io import BytesIO

from PIL import Image, ImageDraw

from app.core.logging import get_logger

logger = get_logger(__name__)


def _sample_edge_color(img: Image.Image, sample_size: int = 20) -> tuple[int, int, int]:
    """Sample the dominant color from the edges of the image."""
    w, h = img.size
    pixels = []

    # Sample from all 4 edges
    for x in range(0, w, max(1, w // sample_size)):
        pixels.append(img.getpixel((x, 0)))           # top
        pixels.append(img.getpixel((x, h - 1)))       # bottom
    for y in range(0, h, max(1, h // sample_size)):
        pixels.append(img.getpixel((0, y)))            # left
        pixels.append(img.getpixel((w - 1, y)))        # right

    # Average the sampled colors
    if not pixels:
        return (255, 255, 255)

    r = sum(p[0] for p in pixels) // len(pixels)
    g = sum(p[1] for p in pixels) // len(pixels)
    b = sum(p[2] for p in pixels) // len(pixels)
    return (r, g, b)


def _color_distance(c1: tuple, c2: tuple) -> float:
    """Euclidean distance between two RGB colors."""
    return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2) ** 0.5


def remove_background(photo_bytes: bytes, tolerance: int = 50) -> bytes:
    """
    Remove the background from a product photo.

    Detects the edge color (usually white/gray), then makes all pixels
    within `tolerance` of that color transparent. Uses flood-fill from
    edges so only the outer background is removed, not internal areas.

    Args:
        photo_bytes: input JPEG/PNG bytes
        tolerance: color distance threshold (0-255). Higher = more aggressive.
                   50 works well for white/light gray backgrounds.

    Returns:
        PNG bytes with transparent background.
    """
    try:
        img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    except Exception as exc:
        logger.warning("bg_remove: failed to open image: %s", exc)
        return photo_bytes  # return original on failure

    w, h = img.size
    bg_color = _sample_edge_color(img)

    # Check if background is light enough to remove
    brightness = (bg_color[0] + bg_color[1] + bg_color[2]) / 3
    if brightness < 100:
        # Dark background — don't remove, it'll look fine on dark cards
        logger.info("bg_remove: dark background (brightness=%.0f), skipping", brightness)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    logger.info("bg_remove: detected bg color=(%d,%d,%d) brightness=%.0f", *bg_color, brightness)

    # Convert to RGBA
    img_rgba = img.convert("RGBA")
    pixels = img_rgba.load()

    # Flood fill from edges — mark background pixels
    visited = set()
    queue = []

    # Seed from all edge pixels
    for x in range(w):
        queue.append((x, 0))
        queue.append((x, h - 1))
    for y in range(h):
        queue.append((0, y))
        queue.append((w - 1, y))

    bg_pixels = set()

    while queue:
        x, y = queue.pop()
        if (x, y) in visited:
            continue
        if x < 0 or x >= w or y < 0 or y >= h:
            continue
        visited.add((x, y))

        pixel = pixels[x, y]
        dist = _color_distance(pixel[:3], bg_color)

        if dist <= tolerance:
            bg_pixels.add((x, y))
            # Add neighbors (4-connected for speed)
            queue.append((x + 1, y))
            queue.append((x - 1, y))
            queue.append((x, y + 1))
            queue.append((x, y - 1))

    # Make background pixels transparent with soft edges
    for x, y in bg_pixels:
        pixels[x, y] = (0, 0, 0, 0)

    # Soft edge: pixels near the boundary get partial transparency
    edge_pixels = set()
    for x, y in bg_pixels:
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in bg_pixels:
                edge_pixels.add((nx, ny))

    # Apply feathering to edge pixels (2px soft edge)
    for _ in range(2):
        new_edge = set()
        for x, y in edge_pixels:
            pixel = pixels[x, y]
            if pixel[3] > 0:
                pixels[x, y] = (pixel[0], pixel[1], pixel[2], pixel[3] // 2)
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in bg_pixels and (nx, ny) not in edge_pixels:
                        new_edge.add((nx, ny))
        edge_pixels = new_edge

    removed_pct = len(bg_pixels) / (w * h) * 100
    logger.info("bg_remove: removed %d pixels (%.1f%% of image)", len(bg_pixels), removed_pct)

    buf = BytesIO()
    img_rgba.save(buf, format="PNG")
    return buf.getvalue()
