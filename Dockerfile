FROM python:3.12-slim

RUN useradd --create-home --uid 1000 registry
WORKDIR /app

COPY registry/ registry/
COPY verifier/ verifier/
COPY api/ api/
COPY agents/ agents/
COPY cli.py .

RUN mkdir -p /data && chown registry:registry /data
VOLUME /data
ENV REGISTRY_DB=/data/registry.db

USER registry
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"

CMD ["python", "api/start.py", "--host", "0.0.0.0", "--port", "8080"]
