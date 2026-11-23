FROM python:3.11-alpine

WORKDIR /app

# Install system dependencies (minimal)
RUN apk add --no-cache \
    ffmpeg \
    gcc \
    musl-dev \
    postgresql-client \
    postgresql-libs \
    tzdata

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies with minimal cache
RUN pip install --no-cache-dir -r requirements.txt

# Create the non-root user before copying the code so ownership is set by
# COPY --chown in the same layer, instead of a recursive chown that rewrites
# every file into an extra layer on each deploy.
RUN adduser -D diver && chown diver:diver /app

# Copy application code
COPY --chown=diver:diver . .
USER diver

# Health check (BusyBox wget avoids spawning Python + requests every 10s;
# -Y off bypasses any http_proxy env var so loopback probes stay direct)
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD wget -q -Y off -T 2 -O /dev/null http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
