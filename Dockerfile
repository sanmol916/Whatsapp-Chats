# One-command local run with Docker. See docker-compose.yml.
FROM python:3.11-slim

WORKDIR /app

# Install deps first (better layer caching).
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code (app package + static panel).
COPY backend/ ./

# Store the database + extracted media on a mounted volume.
ENV WA_STORAGE_DIR=/data
VOLUME ["/data"]

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "300"]
