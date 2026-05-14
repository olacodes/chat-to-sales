"""
app/infra/status_video.py

Generate Ken Burns effect videos from product photos for WhatsApp Status.

Takes a product image → applies slow zoom/pan → overlays text → outputs MP4.
Requires FFmpeg installed (already in Dockerfile).

Output: 1080x1920 MP4, H.264, 5 seconds, ~300-600KB.
"""

import asyncio
import os
import tempfile
from io import BytesIO

from PIL import Image

from app.core.logging import get_logger

logger = get_logger(__name__)

_WIDTH = 1080
_HEIGHT = 1920
_DURATION = 5  # seconds
_FPS = 30


def _prepare_input_image(photo_bytes: bytes) -> bytes:
    """
    Resize and pad the input photo to fill 1080x1920 (9:16 portrait).

    Returns JPEG bytes of the prepared image.
    """
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")

    # Scale to cover the canvas
    photo_ratio = img.width / img.height
    canvas_ratio = _WIDTH / _HEIGHT
    if photo_ratio > canvas_ratio:
        new_height = _HEIGHT
        new_width = int(_HEIGHT * photo_ratio)
    else:
        new_width = _WIDTH
        new_height = int(_WIDTH / photo_ratio)

    img = img.resize((new_width, new_height), Image.LANCZOS)

    # Center crop
    left = (new_width - _WIDTH) // 2
    top = (new_height - _HEIGHT) // 2
    img = img.crop((left, top, left + _WIDTH, top + _HEIGHT))

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _get_zoompan_filter(effect: str) -> str:
    """
    Return the FFmpeg zoompan filter string for the given effect.

    All effects produce 1080x1920 output at 30fps for 5 seconds.
    """
    total_frames = _DURATION * _FPS  # 150 frames

    if effect == "zoom_in":
        # Slow zoom from 100% to 130%, centered
        return (
            f"zoompan=z='min(zoom+0.002,1.3)':d={total_frames}"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={_WIDTH}x{_HEIGHT}:fps={_FPS}"
        )
    elif effect == "zoom_out":
        # Start at 130%, zoom out to 100%
        return (
            f"zoompan=z='if(eq(on,1),1.3,max(zoom-0.002,1.0))':d={total_frames}"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={_WIDTH}x{_HEIGHT}:fps={_FPS}"
        )
    elif effect == "pan_right":
        # Slow pan from left to right at slight zoom
        return (
            f"zoompan=z='1.15':d={total_frames}"
            f":x='(iw-iw/zoom)*on/{total_frames}':y='ih/2-(ih/zoom/2)'"
            f":s={_WIDTH}x{_HEIGHT}:fps={_FPS}"
        )
    elif effect == "pan_down":
        # Slow pan from top to bottom at slight zoom
        return (
            f"zoompan=z='1.15':d={total_frames}"
            f":x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*on/{total_frames}'"
            f":s={_WIDTH}x{_HEIGHT}:fps={_FPS}"
        )
    else:
        # Default: zoom in
        return _get_zoompan_filter("zoom_in")


def _build_drawtext_filters(
    product_name: str,
    price: str,
    trader_name: str,
    store_url: str,
) -> str:
    """Build FFmpeg drawtext filter chain for text overlays."""
    # Escape special characters for FFmpeg
    def esc(text: str) -> str:
        return text.replace("'", "\\'").replace(":", "\\:").replace("\\", "\\\\")

    filters = []

    # Dark gradient overlay at top and bottom for readability
    filters.append(
        "drawbox=x=0:y=0:w=iw:h=ih*0.35:color=black@0.5:t=fill"
    )
    filters.append(
        "drawbox=x=0:y=ih*0.65:w=iw:h=ih*0.35:color=black@0.5:t=fill"
    )

    # Trader name (top)
    filters.append(
        f"drawtext=text='{esc(trader_name.upper())}':"
        f"fontsize=40:fontcolor=white@0.8:"
        f"x=(w-text_w)/2:y=h*0.08:"
        f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    )

    # Product name (center-upper)
    filters.append(
        f"drawtext=text='{esc(product_name)}':"
        f"fontsize=60:fontcolor=white:"
        f"x=(w-text_w)/2:y=h*0.40:"
        f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    )

    # Price (center, green)
    filters.append(
        f"drawtext=text='{esc(price)}':"
        f"fontsize=80:fontcolor=#25D366:"
        f"x=(w-text_w)/2:y=h*0.50:"
        f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    )

    # Store URL (bottom area)
    filters.append(
        f"drawtext=text='{esc(store_url)}':"
        f"fontsize=30:fontcolor=white@0.7:"
        f"x=(w-text_w)/2:y=h*0.85:"
        f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )

    # CTA
    filters.append(
        f"drawtext=text='Message to order':"
        f"fontsize=36:fontcolor=white:"
        f"x=(w-text_w)/2:y=h*0.90:"
        f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    )

    return ",".join(filters)


async def generate_ken_burns_video(
    *,
    photo_bytes: bytes,
    product_name: str,
    price: int,
    trader_name: str,
    store_url: str,
    effect: str = "zoom_in",
) -> bytes | None:
    """
    Generate a Ken Burns effect video from a product photo.

    Returns MP4 bytes on success, None on failure (FFmpeg missing or error).
    """
    try:
        # Prepare input image (resize to 1080x1920)
        prepared = _prepare_input_image(photo_bytes)
    except Exception as exc:
        logger.warning("Failed to prepare image for video: %s", exc)
        return None

    # Write temp files
    tmp_input = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp_output = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    try:
        tmp_input.write(prepared)
        tmp_input.close()
        tmp_output.close()

        # Build FFmpeg command
        zoompan = _get_zoompan_filter(effect)
        drawtext = _build_drawtext_filters(
            product_name=product_name,
            price=f"N{price:,}",
            trader_name=trader_name,
            store_url=store_url,
        )

        # Full filter: zoompan for Ken Burns, then drawtext for overlays
        vf = f"{zoompan},{drawtext}"

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", tmp_input.name,
            "-vf", vf,
            "-t", str(_DURATION),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "28",
            "-pix_fmt", "yuv420p",
            "-an",  # no audio
            "-movflags", "+faststart",
            tmp_output.name,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            logger.warning(
                "FFmpeg Ken Burns failed (code %d): %s",
                proc.returncode,
                stderr.decode()[:500],
            )
            return None

        # Read output
        with open(tmp_output.name, "rb") as f:
            video_bytes = f.read()

        if len(video_bytes) < 1000:
            logger.warning("Ken Burns video too small (%d bytes) — likely corrupt", len(video_bytes))
            return None

        logger.info(
            "Ken Burns video generated: %d bytes, effect=%s, product=%s",
            len(video_bytes), effect, product_name,
        )
        return video_bytes

    except FileNotFoundError:
        logger.warning("FFmpeg not found — Ken Burns video generation skipped")
        return None
    except asyncio.TimeoutError:
        logger.warning("FFmpeg Ken Burns timed out after 30s")
        return None
    except Exception as exc:
        logger.warning("Ken Burns video generation error: %s", exc)
        return None
    finally:
        # Cleanup temp files
        for f in (tmp_input.name, tmp_output.name):
            try:
                os.unlink(f)
            except OSError:
                pass


# Effect rotation — deterministic per day
EFFECTS = ["zoom_in", "zoom_out", "pan_right", "pan_down"]


def pick_effect(day_index: int, product_index: int = 0) -> str:
    """Pick a Ken Burns effect deterministically based on day + product index."""
    return EFFECTS[(day_index + product_index) % len(EFFECTS)]
