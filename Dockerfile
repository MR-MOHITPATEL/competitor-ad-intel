FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (server version — no Playwright)
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# Copy app source
COPY . .

# Create data directories (will be overridden by persistent disk mount on Render)
RUN mkdir -p data/raw/master data/raw/images data/scored data/analyzed

# Streamlit config
ENV PYTHONUNBUFFERED=1
EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "dashboard/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
