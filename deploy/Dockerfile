# Core service image. Built on the dev instance from a git checkout (deploy/remote-deploy.sh);
# the build context is limited by the allowlist in /.dockerignore.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY core/requirements.txt core/requirements.txt
RUN pip install -r core/requirements.txt

COPY core/app core/app

RUN useradd --system --uid 10001 --no-create-home app
USER app

EXPOSE 8000

# One worker process: the service keeps its own pool of at most 2 database connections.
# Behind Caddy on the same host; the port is published on 127.0.0.1 only.
CMD ["uvicorn", "core.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
