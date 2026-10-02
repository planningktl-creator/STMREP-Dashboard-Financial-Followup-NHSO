FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS web
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build
FROM python:3.13-slim@sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TMPDIR=/tmp/stmrep PORT=8000
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY pyproject.toml ./
COPY financial ./financial
COPY repstm ./repstm
COPY scripts ./scripts
RUN pip install --no-cache-dir --no-deps --no-build-isolation . && groupadd --gid 10929 stmrep && useradd --uid 10929 --gid 10929 --create-home stmrep && mkdir -p /app/.data /tmp/stmrep && chown stmrep:stmrep /app/.data /tmp/stmrep
COPY --from=web /build/dist ./frontend/dist
USER 10929:10929
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/healthz',timeout=3)"
CMD ["python","-m","financial.server"]
