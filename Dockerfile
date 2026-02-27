# Dockerfile
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Set work directory
WORKDIR /app

# Install system dependencies (including Tk for GUI and poppler for pdf2image)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libsqlite3-dev \
        python3-tk \
        tk-dev \
        poppler-utils \
        && rm -rf /var/lib/apt/lists/*

# Copy only requirements first (leverages Docker cache)
COPY requirements.txt .
# Install Python dependencies (pywin32/win32printing are skipped on Linux via platform markers)
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create required directories with correct ownership
RUN mkdir -p /app/database /app/logs /app/config && \
    chown -R appuser:appuser /app /app/database /app/logs /app/config

# Switch to non-root user
USER appuser

# Expose port (if you add Flask/FastAPI later)
# EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import sys, pathlib; sys.exit(0 if pathlib.Path('database/ream_management.db').exists() else 1)" || exit 1

# Note: This is a GUI application. Running in Docker requires X11 forwarding
# or a virtual framebuffer (Xvfb). For headless/server use, consider adding
# a web API layer.
CMD ["python", "main.py"]