FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# `apt-get upgrade` is deliberate, not boilerplate. The security workflow scans this
# image with Trivy at CRITICAL,HIGH and fails the build, but the packages it flags are
# almost always base-image packages, not ones we install — and the upstream
# `python:3.12-slim` tag is rebuilt on its own schedule, so pinning a newer tag does not
# reliably pick up a Debian security update. Upgrading here applies whatever is in the
# security suite at build time, which is what actually clears the scan.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
        curl \
    && apt-get upgrade -y --no-install-recommends \
        util-linux \
        bsdutils \
        libblkid1 \
        libfdisk1 \
        libmount1 \
        libsmartcols1 \
        libuuid1 \
        mount \
        uuid-runtime \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip uninstall -y pip

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
