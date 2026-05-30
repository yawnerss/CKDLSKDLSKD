FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies and Chromium browser
RUN apt-get update && apt-get install -y \
    chromium-browser \
    chromium-codecs-ffmpeg \
    libxss1 \
    libappindicator1 \
    libindicator7 \
    fonts-liberation \
    libnss3 \
    lsb-release \
    xdg-utils \
    libgbm1 \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Set Chrome as default for SeleniumBase
ENV PATH="/usr/bin:${PATH}"
ENV SB_NO_SANDBOX=true
ENV DISPLAY=:99

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy application
COPY cf_api.py .

# Create cache directory
RUN mkdir -p /app/chrome_cache

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uvicorn", "cf_api:app", "--host", "0.0.0.0", "--port", "8000"]
