"""
HTML → Video renderer using Playwright + ambient audio.

Records CSS-animated HTML templates as video using Playwright's
native video recording. Generates ambient audio and overlays it.

Pipeline: HTML → Playwright WebM → FFmpeg (+ audio) → MP4
"""

import asyncio
import os
import random
import tempfile

from app.core.logging import get_logger

logger = get_logger(__name__)

_VIEWPORT = {"width": 1080, "height": 1920}
_VIDEO_DURATION_MS = 6000  # 6 seconds
_AUDIO_DIR = "/opt/audio"

# ── Ambient audio generation ─────────────────────────────────────────────────

_AUDIO_PRESETS = [
    {
        # Warm ambient pad — filtered pink noise
        "name": "warm",
        "filter": (
            "anoisesrc=d=7:c=pink:r=44100,"
            "lowpass=f=600,"
            "highpass=f=80,"
            "volume=0.08,"
            "afade=t=in:d=0.8,"
            "afade=t=out:st=5.5:d=1.5"
        ),
    },
    {
        # Soft tone — layered sine waves (C major chord, very quiet)
        "name": "tone",
        "filter": (
            "sine=f=261.6:d=7[c];"
            "sine=f=329.6:d=7[e];"
            "sine=f=392.0:d=7[g];"
            "[c][e]amix=inputs=2[ce];"
            "[ce][g]amix=inputs=2,"
            "volume=0.04,"
            "lowpass=f=2000,"
            "afade=t=in:d=1.0,"
            "afade=t=out:st=5.5:d=1.5"
        ),
    },
    {
        # Gentle hum — brown noise, very filtered
        "name": "hum",
        "filter": (
            "anoisesrc=d=7:c=brown:r=44100,"
            "lowpass=f=400,"
            "highpass=f=60,"
            "volume=0.06,"
            "afade=t=in:d=1.0,"
            "afade=t=out:st=5.5:d=1.5"
        ),
    },
]


async def _generate_ambient_audio(output_path: str, preset: dict | None = None) -> bool:
    """Generate a short ambient audio clip using FFmpeg synthesis."""
    if preset is None:
        preset = random.choice(_AUDIO_PRESETS)

    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", preset["filter"],
            "-c:a", "aac",
            "-b:a", "64k",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)

        if proc.returncode != 0:
            logger.warning("Audio generation failed: %s", stderr.decode()[:200])
            return False

        logger.info("Ambient audio generated: preset=%s path=%s", preset["name"], output_path)
        return True

    except Exception as exc:
        logger.warning("Audio generation error: %s", exc)
        return False


# ── Video rendering ──────────────────────────────────────────────────────────

async def render_video(
    *,
    html: str,
    duration_ms: int = _VIDEO_DURATION_MS,
    with_audio: bool = True,
) -> bytes | None:
    """
    Render an animated HTML template to MP4 video with ambient audio.

    Pipeline:
    1. Playwright records animated page → WebM
    2. FFmpeg generates ambient audio
    3. FFmpeg merges video + audio → MP4 (H.264 + AAC)

    Returns MP4 bytes on success, None on failure.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed — video rendering unavailable")
        return None

    tmp_dir = tempfile.mkdtemp()
    mp4_silent = os.path.join(tmp_dir, "silent.mp4")
    audio_path = os.path.join(tmp_dir, "ambient.m4a")
    mp4_final = os.path.join(tmp_dir, "final.mp4")

    try:
        # ── Step 1: Record animated page ─────────────────────────────────
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
            await page.set_content(html, wait_until="networkidle")
            await page.wait_for_timeout(800)

            # Trigger animations
            await page.evaluate("document.querySelector('.ad').classList.add('animate')")
            await page.wait_for_timeout(duration_ms)

            await context.close()
            await browser.close()

        # Find the recorded WebM
        webm_files = [f for f in os.listdir(tmp_dir) if f.endswith(".webm")]
        if not webm_files:
            logger.warning("No WebM video file found after recording")
            return None
        webm_path = os.path.join(tmp_dir, webm_files[0])

        # ── Step 2: Convert WebM → silent MP4 ────────────────────────────
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", webm_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "26",
            "-pix_fmt", "yuv420p", "-an",
            "-movflags", "+faststart",
            mp4_silent,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            logger.warning("FFmpeg WebM→MP4 failed: %s", stderr.decode()[:300])
            return None

        # ── Step 3: Generate ambient audio + merge ────────────────────────
        if with_audio:
            audio_ok = await _generate_ambient_audio(audio_path)
            if audio_ok:
                proc2 = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y",
                    "-i", mp4_silent,
                    "-i", audio_path,
                    "-c:v", "copy",  # no re-encode video
                    "-c:a", "aac", "-b:a", "64k",
                    "-shortest",
                    "-movflags", "+faststart",
                    mp4_final,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr2 = await asyncio.wait_for(proc2.communicate(), timeout=15)
                if proc2.returncode == 0:
                    output_path = mp4_final
                    logger.info("Audio merged into video")
                else:
                    logger.warning("Audio merge failed, using silent video: %s", stderr2.decode()[:200])
                    output_path = mp4_silent
            else:
                output_path = mp4_silent
        else:
            output_path = mp4_silent

        # ── Read final output ─────────────────────────────────────────────
        with open(output_path, "rb") as f:
            mp4_bytes = f.read()

        if len(mp4_bytes) < 1000:
            logger.warning("Video too small (%d bytes)", len(mp4_bytes))
            return None

        logger.info("Video rendered: %d bytes (audio=%s)", len(mp4_bytes), with_audio and output_path == mp4_final)
        return mp4_bytes

    except Exception as exc:
        logger.error("Video render failed: %s", exc)
        return None
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
