# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build tools required by some C-extension packages (asyncpg, hiredis,
# cryptography/bcrypt via python-jose and passlib)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first — leverage Docker layer cache
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# ffmpeg for audio conversion, fonts for Status Kit image generation,
# Playwright Chromium deps for HTML template rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
        # Chromium deps for Playwright
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
        libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Install Playwright Chromium (must be after user creation, with writable cache)
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN pip install playwright==1.52.0 \
    && mkdir -p /opt/playwright \
    && playwright install chromium \
    && chmod -R 755 /opt/playwright

# Pre-download rembg U2-Net model so first image upload doesn't take 2 min
RUN pip install rembg[cpu]==2.0.57 \
    && python -c "from rembg import new_session; new_session('u2net')" 2>/dev/null || true

WORKDIR /app

# Copy pre-built site-packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY --chown=appuser:appgroup . .

USER appuser

# Expose the application port
EXPOSE 8000

# Health check — Docker / orchestrators will restart on failure
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Production-grade uvicorn command:
#   --workers 1       (increase behind a load balancer or swap for gunicorn+uvicorn)
#   --no-access-log   (structured logging is handled by the app)
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--no-access-log"]
