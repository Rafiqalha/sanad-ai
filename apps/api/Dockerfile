# The build context is the repository ROOT, not this directory, because the
# service depends on the sanad-core library which lives outside apps/api.
# Build with:  docker build -f apps/api/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# requirements.txt points at packages/sanad-core with a path relative to the
# working directory, so WORKDIR must stay at the workspace root and the library
# must be copied before pip runs. Copying both manifests first keeps the
# dependency install cached across code changes.
COPY packages/sanad-core ./packages/sanad-core
COPY apps/api/requirements.txt ./apps/api/requirements.txt
RUN pip install --no-cache-dir -r apps/api/requirements.txt

COPY apps/api ./apps/api

WORKDIR /srv/apps/api
EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
