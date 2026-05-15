"""
HTML → Video renderer using Playwright.

Records CSS-animated HTML templates as video using Playwright's
native video recording. Each template animates elements sequentially
over 5-6 seconds → saved as WebM → converted to MP4 via FFmpeg.
"""

import asyncio
import os
import tempfile

from app.core.logging import get_logger

logger = get_logger(__name__)

_VIEWPORT = {"width": 1080, "height": 1920}
_VIDEO_DURATION_MS = 6000  # 6 seconds for animations to complete


async def render_video(
    *,
    html: str,
    duration_ms: int = _VIDEO_DURATION_MS,
) -> bytes | None:
    """
    Render an animated HTML template to MP4 video bytes.

    1. Playwright opens page with record_video enabled
    2. Sets animated HTML content
    3. Waits for animation duration
    4. Closes context → video saved as WebM
    5. FFmpeg converts WebM → MP4 (WhatsApp compatible)

    Returns MP4 bytes on success, None on failure.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed — video rendering unavailable")
        return None

    tmp_dir = tempfile.mkdtemp()
    mp4_path = os.path.join(tmp_dir, "output.mp4")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                viewport=_VIEWPORT,
                record_video_dir=tmp_dir,
                record_video_size=_VIEWPORT,
            )
            page = await context.new_page()

            # Load animated HTML
            await page.set_content(html, wait_until="networkidle")

            # Wait for fonts to load
            await page.wait_for_timeout(800)

            # Trigger animations by adding a class
            await page.evaluate("document.querySelector('.ad').classList.add('animate')")

            # Wait for animations to complete
            await page.wait_for_timeout(duration_ms)

            # Close to save the video
            await context.close()
            await browser.close()

        # Find the recorded WebM file
        webm_files = [f for f in os.listdir(tmp_dir) if f.endswith(".webm")]
        if not webm_files:
            logger.warning("No WebM video file found after recording")
            return None

        webm_path = os.path.join(tmp_dir, webm_files[0])

        # Convert WebM → MP4 (WhatsApp requires MP4/H.264)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", webm_path,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "26",
            "-pix_fmt", "yuv420p",
            "-an",  # no audio
            "-movflags", "+faststart",
            mp4_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            logger.warning("FFmpeg WebM→MP4 failed: %s", stderr.decode()[:300])
            return None

        with open(mp4_path, "rb") as f:
            mp4_bytes = f.read()

        if len(mp4_bytes) < 1000:
            logger.warning("Video too small (%d bytes)", len(mp4_bytes))
            return None

        logger.info("Video rendered: %d bytes", len(mp4_bytes))
        return mp4_bytes

    except Exception as exc:
        logger.error("Video render failed: %s", exc)
        return None
    finally:
        # Cleanup temp files
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
