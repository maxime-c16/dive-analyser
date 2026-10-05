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

# Copy application code
COPY . .

# Create non-root user for security (optional but good practice)
RUN adduser -D diver && chown -R diver:diver /app
USER diver

# Health check
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD python -c "import requests; response = requests.get('http://localhost:8000/health', timeout=2); response.raise_for_status()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
