FROM python:3.11-slim

WORKDIR /app

# curl is needed for the healthcheck; the rest are installed by playwright --with-deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# Install Chromium browser + all its Linux system dependencies in one step
RUN playwright install --with-deps chromium

# Copy app source
COPY . .

# Create data directories (ephemeral on Railway — Supabase is the real store)
RUN mkdir -p data/raw/master data/raw/images data/scored data/analyzed

ENV PYTHONUNBUFFERED=1

EXPOSE 8501

# Use ${PORT:-8501}: Railway injects $PORT; fallback to 8501 for local docker run
HEALTHCHECK CMD curl --fail http://localhost:${PORT:-8501}/_stcore/health || exit 1

# Shell form (not exec/JSON form) so ${PORT:-8501} is expanded at container start
CMD streamlit run dashboard/app.py \
    --server.port=${PORT:-8501} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
