# Multi-arch base image (supports linux/arm64 for Raspberry Pi & linux/amd64)
FROM python:3.11-slim-bookworm

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HEADLESS=true \
    SCAN_FPS=15

# Install system dependencies:
# - libzbar0: required by pyzbar for QR decoding
# - libglib2.0-0: required by OpenCV
# - v4l-utils: video device utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    libzbar0 \
    libglib2.0-0 \
    v4l-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python packages (opencv-python-headless is lightweight & avoids X11/GUI bloat)
RUN pip install --no-cache-dir \
    opencv-python-headless>=4.8.0 \
    pyzbar>=0.1.9 \
    requests>=2.31.0

# Copy application files
COPY qr_telegram.py /app/
COPY .env /app/.env

# Run scanner directly
CMD ["python", "qr_telegram.py"]
