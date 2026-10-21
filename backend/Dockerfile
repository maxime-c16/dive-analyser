FROM python:3.11-alpine

WORKDIR /app

# Install system dependencies (minimal)
RUN apk add --no-cache \
    ffmpeg \
    gcc \
    musl-dev \
    postgresql-client \
    postgresql-libs

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

# Health check
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD python -c "import requests; response = requests.get('http://localhost:8000/health', timeout=2); response.raise_for_status()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
