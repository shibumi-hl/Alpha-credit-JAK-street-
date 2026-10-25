FROM node:22.11.0-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.13.1-slim
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --create-home app
COPY deploy/requirements-server.txt deploy/requirements-server.txt
RUN pip install --no-cache-dir -r deploy/requirements-server.txt
COPY --chown=app:app api/ ./api/
COPY --chown=app:app scoring/ ./scoring/
COPY --chown=app:app config/ ./config/
COPY --chown=app:app demo/ ./demo/
COPY --chown=app:app models/ ./models/
COPY --from=web --chown=app:app /web/dist /app/web/dist
ENV ENGINE_PATH=/app/models/engine.pkl \
    WEB_DIST=/app/web/dist \
    PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).close()"]
CMD ["uvicorn", "--factory", "api.app:create_app", "--host", "0.0.0.0", "--port", "8000"]
