FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/OWNER/ptero-monitor"
LABEL org.opencontainers.image.description="Pterodactyl Panel Server Monitor - Auto Keep-Alive"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app.py .
COPY static/ ./static/

# Create data directory
RUN mkdir -p /app/data

ENV PORT=8000
ENV DB_PATH=/app/data/monitor.db

EXPOSE 8000

VOLUME ["/app/data"]

CMD ["python", "app.py"]
