FROM node:26.13.1-trixie-slim@sha256:e6bedef217677b276c591795e169840edd9096dbf13f29df8ef8d1856b8820bc AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run typecheck && npm run build

FROM python:3.15.2-slim-trixie@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_COMPILE_BYTECODE=1 \
    PATH=/app/.venv/bin:$PATH PYTHONPATH=/app/backend DATA_ROOT=/data SPA_ROOT=/app/frontend \
    DJANGO_SETTINGS_MODULE=config.settings HOME=/tmp
WORKDIR /app
# PDFium's shared C++ runtime. Package release pinned, base image pinned above.
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6=14.2.0-19 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.13.9 \
    && useradd --uid 1000 --create-home accountant \
    && mkdir /data && chown accountant:accountant /data
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY skills/ ./skills/
COPY --from=frontend /build/build/client/ ./frontend/
RUN python backend/manage.py collectstatic --noinput && chown -R accountant:accountant /app
USER accountant
EXPOSE 8000
ENTRYPOINT ["/bin/sh", "/app/scripts/entrypoint.sh"]
CMD ["web"]
