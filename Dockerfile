# --- build the React app ---
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Flask API serving the built app ---
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 STATIC_DIR=/app/static
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist ./static
RUN useradd --create-home app && chown -R app /app
USER app
EXPOSE 8000
CMD ["sh", "-c", "gunicorn wsgi:app --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 120"]
