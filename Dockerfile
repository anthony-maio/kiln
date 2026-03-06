FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn

# Copy application files
COPY api_server.py .
COPY index.html .
COPY base.css .
COPY style.css .
COPY app.js .

# Create data directory for SQLite
RUN mkdir -p /app/data

# Set environment variable for DB path
ENV KILN_DB_PATH=/app/data/kiln.db

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["python", "-m", "uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
